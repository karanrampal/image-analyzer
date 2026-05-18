output "alert_policy_name" {
  description = "The full resource name of the alert policy."
  value       = google_monitoring_alert_policy.cr_job_failed.name
}

output "email_channel_names" {
  description = "The full resource names of the email notification channels."
  value       = [for ch in google_monitoring_notification_channel.email : ch.name]
}
