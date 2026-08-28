variable "project_id" {
  description = "The Google Cloud project. Never the Gemini key project — see README."
  type        = string
  default     = "praetor-run-2026"

  validation {
    # gen-lang-client-0515700308 must stay billing-disabled, and nothing here should be
    # able to attach it to anything. Enforced rather than documented.
    condition     = !startswith(var.project_id, "gen-lang-client")
    error_message = "The Gemini API key project must stay out of Terraform and stay billing-disabled."
  }
}

variable "region" {
  description = "Everything is single-region. Document AI's invoice parser is here."
  type        = string
  default     = "asia-south1"
}

variable "environment" {
  description = "The only difference between staging and production."
  type        = string
  default     = "production"

  validation {
    condition     = contains(["production", "staging"], var.environment)
    error_message = "environment must be production or staging."
  }
}

variable "inbox_bucket" {
  description = "Where a PDF lands to start the pipeline."
  type        = string
  default     = "praetor-inbox-2026"
}

# Two images, not one, and the plan is what taught us that.
#
# The two services run the same Dockerfile with different entrypoints, so "one image, two
# entrypoints" was the intent -- but they were deployed separately with `gcloud run deploy
# --source`, which built and pushed a SEPARATE image for each. Describing them as one
# would have retagged the live queue with the ingest image on the first apply. The plan
# said so before anything ran, which is the entire argument for reading one.
variable "queue_image" {
  description = "Container for the review queue service."
  type        = string
  default     = "asia-south1-docker.pkg.dev/praetor-run-2026/cloud-run-source-deploy/praetor:latest"
}

variable "ingest_image" {
  description = "Container for the ingest service."
  type        = string
  default     = "asia-south1-docker.pkg.dev/praetor-run-2026/cloud-run-source-deploy/praetor-ingest:latest"
}

variable "ingest_budget_inr" {
  description = "Ceiling praetor/costguard.py enforces inside the ingest service."
  type        = string
  default     = "200"
}

variable "retention_days" {
  description = "How long an ingested document is kept in the inbox before deletion."
  type        = number
  default     = 90
}

locals {
  # Production keeps the names the live system already uses, so the import blocks match.
  # Staging suffixes everything, so the two can coexist in one project.
  suffix          = var.environment == "production" ? "" : "-${var.environment}"
  ingest_name     = "praetor-ingest${local.suffix}"
  queue_name      = "praetor${local.suffix}"
  bucket_name     = var.environment == "production" ? var.inbox_bucket : "${var.inbox_bucket}-${var.environment}"
  service_account = "${data.google_project.this.number}-compute@developer.gserviceaccount.com"
}

data "google_project" "this" {
  project_id = var.project_id
}
