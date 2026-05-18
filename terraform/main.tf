resource "google_service_account" "cr_job_sa" {
  project      = var.project_id
  account_id   = var.sa_name
  display_name = "Cloud Run Job Service Account"
  description  = "Service account for running Cloud Run jobs"
}

resource "google_project_iam_member" "cr_job_sa_roles" {
  for_each = toset([
    "roles/logging.logWriter",
    "roles/aiplatform.user",
    "roles/bigquery.jobUser",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.cr_job_sa.email}"
}

module "bigquery_dataset" {
  source = "./modules/bigquery"

  project_id  = var.project_id
  dataset_id  = var.bigquery_dataset_id
  location    = var.region
  description = "Dataset for storing Image Analysis results"

  delete_contents_on_destroy = var.environment == "dev" ? true : false

  labels = merge(var.labels, { component = "bigquery-dataset" })

  iam_members = [
    {
      role   = "roles/bigquery.dataEditor"
      member = "serviceAccount:${google_service_account.cr_job_sa.email}"
    }
  ]
}

module "artifact_registry" {
  source = "./modules/artifact_registry"

  project_id    = var.project_id
  location      = var.region
  repository_id = var.artifact_registry_name
  description   = "Docker repository for container images"

  cleanup_policies = [
    {
      id     = "delete-old-untagged"
      action = "DELETE"
      condition = {
        tag_state  = "UNTAGGED"
        older_than = "30d"
      }
    },
    {
      id     = "keep-last-10"
      action = "KEEP"
      most_recent_versions = {
        keep_count = 10
      }
    }
  ]

  labels = merge(var.labels, { component = "artifact-registry" })
}

module "monitoring" {
  source = "./modules/monitoring"

  project_id        = var.project_id
  environment       = var.environment
  job_name          = var.cr_job_name
  alert_emails      = var.alert_emails

  labels = merge(var.labels, { component = "monitoring" })
}
