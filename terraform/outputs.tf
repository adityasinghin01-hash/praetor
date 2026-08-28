output "ingest_url" {
  description = "Where Eventarc and the sweep post."
  value       = google_cloud_run_v2_service.ingest.uri
}

output "queue_url" {
  description = "The review queue a person opens."
  value       = google_cloud_run_v2_service.queue.uri
}

output "inbox" {
  description = "Drop a PDF here to start the pipeline."
  value       = "gs://${google_storage_bucket.inbox.name}"
}

output "environment" {
  value = var.environment
}
