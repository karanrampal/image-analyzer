variable "project_id" {
  description = "The GCP project ID."
  type        = string
}

variable "environment" {
  description = "The environment (dev, prod, etc.)"
  type        = string

  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be one of: dev, prod."
  }
}

variable "region" {
  description = "The GCP region for the Cloud Run service."
  type        = string
}

variable "sa_name" {
  description = "The name of the service account."
  type        = string
}

variable "artifact_registry_name" {
  description = "The name/ID of the Artifact Registry repository."
  type        = string
}

variable "bigquery_dataset_id" {
  description = "The ID of the BigQuery dataset where results will be stored."
  type        = string
}

variable "labels" {
  description = "Labels to apply to the resources."
  type        = map(string)
  default     = {}
}

variable "cr_job_name" {
  description = "The Cloud Run job name to monitor."
  type        = string
}

variable "alert_emails" {
  description = "List of email addresses to send Cloud Monitoring alert notifications to."
  type        = list(string)
  default     = []
}
