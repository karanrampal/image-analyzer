output "dataset_id" {
  description = "The short dataset ID"
  value       = google_bigquery_dataset.dataset.dataset_id
}

output "dataset_qualified_id" {
  description = "The fully-qualified BigQuery dataset ID in project:dataset format"
  value       = "${google_bigquery_dataset.dataset.project}:${google_bigquery_dataset.dataset.dataset_id}"
}
