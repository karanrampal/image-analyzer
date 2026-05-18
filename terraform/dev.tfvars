# Project configuration
project_id  = "hm-studios-metadata-c54a"
region      = "europe-west1"
environment = "dev"

# Service accounts
sa_name = "cr-job-sa-dev"

# Artifact Registry
artifact_registry_name = "annotate-ar-dev"

# BigQuery
bigquery_dataset_id = "img_annotations_trf"

# Cloud Run Job
cr_job_name = "annotate-images-dev"

# Monitoring
alert_emails = ["karan.rampal@hm.com"]

# Labels
labels = {
  environment = "dev"
  managed-by  = "terraform"
}
