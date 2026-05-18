output "repository_id" {
  description = "The fully-qualified resource ID of the artifact registry repository"
  value       = module.artifact_registry.repository_id
}

output "repository_url" {
  description = "The URL for accessing the artifact registry repository"
  value       = module.artifact_registry.repository_url
}

output "bigquery_dataset_qualified_id" {
  description = "The fully-qualified BigQuery dataset ID in project:dataset format"
  value       = module.bigquery_dataset.dataset_qualified_id
}

output "alert_policy_name" {
  description = "The full resource name of the Cloud Monitoring alert policy."
  value       = module.monitoring.alert_policy_name
}
