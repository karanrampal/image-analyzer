output "repository_id" {
  description = "The fully-qualified resource ID of the repository"
  value       = google_artifact_registry_repository.repository.id
}

output "repository_url" {
  description = "The URL for accessing the repository (format-specific)"
  value       = "${var.location}-${lower(var.format)}.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repository.repository_id}"
}
