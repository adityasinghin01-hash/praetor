# Adopting what already exists.
#
# The live project was built by hand while the pipeline was being worked out. Terraform
# arriving afterwards with an empty state would plan to CREATE all of it, and the first
# casualty would be the running queue. These blocks tell it what is already there.
#
# **Production only.** For a staging environment there is nothing to adopt, so delete or
# ignore this file: `terraform apply -var environment=staging` should create everything.
#
# Read `make tf-plan` before applying, always. A plan that says *create* where you
# expected *import* means a block below is missing or its id is wrong, and applying it
# would duplicate a live resource.

import {
  to = google_storage_bucket.inbox
  id = "praetor-run-2026/praetor-inbox-2026"
}

import {
  to = google_cloud_run_v2_service.ingest
  id = "projects/praetor-run-2026/locations/asia-south1/services/praetor-ingest"
}

import {
  to = google_cloud_run_v2_service.queue
  id = "projects/praetor-run-2026/locations/asia-south1/services/praetor"
}

import {
  to = google_eventarc_trigger.inbox_pdf
  id = "projects/praetor-run-2026/locations/asia-south1/triggers/praetor-inbox-pdf"
}

# NOT importable. The Google provider does not implement import for
# `google_workflows_workflow`, so the live `praetor-sweep` cannot be adopted -- Terraform
# would plan to create it and the apply would fail because the name is taken.
#
# The honest options are: delete the hand-made workflow and let Terraform create it, or
# leave it hand-managed and accept that one resource is outside the code. Neither is
# pretended away here. The resource stays described in main.tf because the description is
# still correct and still the thing you would apply into a fresh project.

import {
  to = google_cloud_scheduler_job.sweep_daily
  id = "projects/praetor-run-2026/locations/asia-south1/jobs/praetor-sweep-daily"
}

import {
  to = google_secret_manager_secret.gemini_api_key
  id = "projects/praetor-run-2026/secrets/gemini-api-key"
}
