terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Deliberately local for now. A remote GCS backend is the right answer the moment more
  # than one person runs this; it is not the right answer while the state has never been
  # applied and would be the only thing in the bucket.
}

provider "google" {
  project = var.project_id
  region  = var.region
}
