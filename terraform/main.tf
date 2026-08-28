# The pipeline: a PDF lands in a bucket and becomes a queue entry a person can work.
#
#   gs://<inbox>  ->  Eventarc  ->  Cloud Run (ingest)  ->  Document AI + the kernel
#                                                        ->  Firestore  ->  the queue
#
# Plus a Workflows sweep on a schedule, because Eventarc's at-least-once is a guarantee
# about duplicates and not about drops.

# --------------------------------------------------------------------------- services

resource "google_project_service" "required" {
  for_each = toset([
    "run.googleapis.com",
    "eventarc.googleapis.com",
    "workflows.googleapis.com",
    "cloudscheduler.googleapis.com",
    "documentai.googleapis.com",
    "firestore.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "pubsub.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "modelarmor.googleapis.com",
  ])

  project = var.project_id
  service = each.value

  # Turning an API off can break a running service, and Terraform destroying an API is
  # rarely what anybody meant.
  disable_on_destroy = false
}

# --------------------------------------------------------------------------- the inbox

resource "google_storage_bucket" "inbox" {
  name     = local.bucket_name
  project  = var.project_id
  location = var.region

  # No object ACLs. Access is IAM only, so "who can read this bucket" has one answer.
  uniform_bucket_level_access = true

  # Retention, and the reason it exists. These are supplier documents: keeping them
  # forever is a growing liability and a growing bill, and deleting them immediately
  # would remove the evidence behind a payment decision. Ninety days outlasts a payment
  # cycle and a dispute about one.
  lifecycle_rule {
    condition { age = var.retention_days }
    action { type = "Delete" }
  }

  # An accidental overwrite or delete is recoverable for a week. The documents are the
  # evidence for a decision somebody may have to defend later.
  versioning { enabled = true }

  lifecycle_rule {
    condition {
      days_since_noncurrent_time = 7
      with_state                 = "ARCHIVED"
    }
    action { type = "Delete" }
  }

  depends_on = [google_project_service.required]
}

# The bucket must never be public. Asserted here as well as tested, because "we did not
# add allUsers" is not the same as "allUsers cannot be added".
resource "google_storage_bucket_iam_binding" "inbox_readers" {
  bucket  = google_storage_bucket.inbox.name
  role    = "roles/storage.objectViewer"
  members = ["serviceAccount:${local.service_account}"]
}

# --------------------------------------------------------------------------- the secret

resource "google_secret_manager_secret" "gemini_api_key" {
  project   = var.project_id
  secret_id = "gemini-api-key${local.suffix}"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

# The VALUE is deliberately not in Terraform. A secret in state is a secret in a file,
# and this state is local. It is set once, by hand:
#
#   printf %s "$KEY" | gcloud secrets versions add gemini-api-key --data-file=-
resource "google_secret_manager_secret_iam_member" "ingest_reads_key" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.gemini_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.service_account}"
}

# --------------------------------------------------------------------------- ingest

resource "google_cloud_run_v2_service" "ingest" {
  name     = local.ingest_name
  project  = var.project_id
  location = var.region

  # Reached only by Eventarc and the sweep, both authenticated. Access is enforced by
  # IAM (`--no-allow-unauthenticated`), NOT by ingress: an earlier draft of this file set
  # ingress to internal-load-balancer, and the plan showed it would have changed the live
  # service and could have stopped Eventarc delivering. Ingress stays as deployed.
  ingress = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = local.service_account

    # Ingestion spends money per page, so the blast radius is bounded here as well as by
    # the ceiling inside the service. Staging gets less of it.
    scaling {
      max_instance_count = var.environment == "production" ? 3 : 1
    }

    containers {
      image   = var.ingest_image
      command = ["python"]
      args    = ["ingest/server.py"]

      # Matching what is deployed. Cloud Run reports CPU in milli-units and sets these
      # two by default; describing them differently would show as drift on every plan,
      # and a plan with permanent noise in it is a plan nobody reads.
      resources {
        limits            = { cpu = "1000m", memory = "1Gi" }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      env {
        name  = "PRAETOR_PROJECT"
        value = var.project_id
      }
      env {
        name  = "PRAETOR_INGEST_READER"
        value = "gemini"
      }
      env {
        name  = "PRAETOR_BUDGET_INR"
        value = var.ingest_budget_inr
      }
      env {
        name = "GOOGLE_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini_api_key.secret_id
            version = "latest"
          }
        }
      }
    }

    timeout = "300s"
  }

  depends_on = [google_project_service.required]
}

# --------------------------------------------------------------------------- the queue

resource "google_cloud_run_v2_service" "queue" {
  name     = local.queue_name
  project  = var.project_id
  location = var.region

  # The only thing a person reaches directly.
  ingress = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = local.service_account

    scaling {
      max_instance_count = var.environment == "production" ? 3 : 1
    }

    containers {
      image = var.queue_image

      resources {
        limits            = { cpu = "1000m", memory = "512Mi" }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      # No model credential here, and that is the point: the queue service cannot spend.
      # Ingestion is a separate service precisely so the two do not share a blast radius.
      env {
        name  = "PRAETOR_BACKEND"
        value = "firestore"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
    }
  }

  depends_on = [google_project_service.required]
}

# --------------------------------------------------------------------------- the trigger

resource "google_eventarc_trigger" "inbox_pdf" {
  name     = "praetor-inbox-pdf${local.suffix}"
  project  = var.project_id
  location = var.region

  matching_criteria {
    attribute = "type"
    value     = "google.cloud.storage.object.v1.finalized"
  }
  matching_criteria {
    attribute = "bucket"
    value     = google_storage_bucket.inbox.name
  }

  destination {
    cloud_run_service {
      service = google_cloud_run_v2_service.ingest.name
      region  = var.region
    }
  }

  service_account = local.service_account

  depends_on = [google_project_service.required]
}

# --------------------------------------------------------------------------- the sweep

resource "google_workflows_workflow" "sweep" {
  name            = "praetor-sweep${local.suffix}"
  project         = var.project_id
  region          = var.region
  service_account = local.service_account

  source_contents = file("${path.module}/../workflows/sweep.yaml")

  depends_on = [google_project_service.required]
}

resource "google_cloud_scheduler_job" "sweep_daily" {
  name      = "praetor-sweep-daily${local.suffix}"
  project   = var.project_id
  region    = var.region
  schedule  = "0 2 * * *"
  time_zone = "Asia/Kolkata"

  # Safe to run repeatedly: ingest/server.py claims one object version at a time inside a
  # Firestore transaction, so a sweep over already-processed documents bills nothing.
  http_target {
    uri         = "https://workflowexecutions.googleapis.com/v1/projects/${var.project_id}/locations/${var.region}/workflows/${google_workflows_workflow.sweep.name}/executions"
    http_method = "POST"
    body        = base64encode("{}")

    oauth_token {
      service_account_email = local.service_account
    }
  }

  depends_on = [google_project_service.required]
}

# --------------------------------------------------------------------------- roles

resource "google_project_iam_member" "runtime" {
  for_each = toset([
    "roles/eventarc.eventReceiver",
    "roles/run.invoker",
    "roles/datastore.user",
    "roles/documentai.apiUser",
    "roles/storage.objectViewer",
    "roles/logging.logWriter",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${local.service_account}"
}

# --------------------------------------------------------------------------- backups
#
# What is actually irreplaceable here is small and specific: the approvals. Everything
# else regenerates -- the corpus is deterministic, the vendor master is derived, the
# exceptions rebuild from `make rules`. An approval is a person's decision at a moment in
# time, it is the SOX segregation-of-duties control (DECISIONS #2), and nothing can
# reconstruct it. The refusal registry and the spend ledger are in the same category.
#
# So this is not "back up the database because one backs up databases". It is: the one
# collection nobody can rebuild lives in Firestore, and Firestore is the only store here
# holding state that is not derived.

resource "google_firestore_backup_schedule" "daily" {
  project  = var.project_id
  database = "(default)"

  # Seven days of dailies. Long enough to notice a bad deploy and recover from it, short
  # enough that supplier data is not accumulating in backups indefinitely -- the bucket
  # lifecycle above deletes documents at 90 days, and a backup that outlives its own
  # retention policy quietly defeats it.
  retention = "604800s" # 7 days

  daily_recurrence {}

  depends_on = [google_project_service.required]
}
