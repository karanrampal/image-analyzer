resource "google_monitoring_notification_channel" "email" {
  for_each = toset(var.alert_emails)

  project      = var.project_id
  display_name = "Email Notifications (${each.value}) - ${var.environment}"
  type         = "email"

  labels = {
    email_address = each.value
  }

  user_labels = var.labels
}

resource "google_monitoring_alert_policy" "cr_job_failed" {
  project      = var.project_id
  display_name = "Cloud Run Job Failed - ${var.environment}"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "Failed executions > 0"
    condition_threshold {
      filter = join(" AND ", [
        "resource.type=\"cloud_run_job\"",
        "metric.type=\"run.googleapis.com/job/completed_execution_count\"",
        "metric.labels.result=\"failed\"",
        "resource.labels.job_name=\"${var.job_name}\"",
      ])
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }

  notification_channels = values(google_monitoring_notification_channel.email)[*].name

  alert_strategy {
    auto_close = "604800s" # 7 days
    notification_rate_limit {
      period = "3600s" # max one notification per hour
    }
  }

  documentation {
    content   = "Cloud Run job `${var.job_name}` in project `${var.project_id}` has failed.\n\nCheck the [GCP Console](https://console.cloud.google.com/run/jobs?project=${var.project_id}) for details."
    mime_type = "text/markdown"
  }

  user_labels = var.labels
}
