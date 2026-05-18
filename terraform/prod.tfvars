# Project configuration
project_id  = "hm-studios-metadata-c54a"
region      = "europe-west1"
environment = "prod"

# Service accounts
sa_name = "cr-job-sa-prod"

# Artifact Registry
artifact_registry_name = "annotate-ar-prod"

# BigQuery
bigquery_dataset_id = "img_annotations_srv"

# Cloud Run Job
cr_job_name = "annotate-images-prod"

# Monitoring
alert_emails = ["karan.rampal@hm.com"]

# Labels
labels = {
  environment = "prod"
  managed-by  = "terraform"
}
