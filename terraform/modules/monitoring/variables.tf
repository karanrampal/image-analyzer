variable "project_id" {
  description = "The GCP project ID."
  type        = string
}

variable "environment" {
  description = "The environment (dev, prod, etc.)."
  type        = string
}

variable "job_name" {
  description = "The Cloud Run job name to monitor."
  type        = string
}

variable "alert_emails" {
  description = "List of email addresses to send alert notifications to."
  type        = list(string)
  default     = []
}

variable "labels" {
  description = "Labels to apply to monitoring resources."
  type        = map(string)
  default     = {}
}
