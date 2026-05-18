resource "google_bigquery_dataset" "dataset" {
  project                    = var.project_id
  dataset_id                 = var.dataset_id
  friendly_name              = var.friendly_name
  description                = var.description
  location                   = var.location
  delete_contents_on_destroy = var.delete_contents_on_destroy

  labels = var.labels
}

locals {
  iam_member_map = {
    for m in var.iam_members :
    "${m.role}|${m.member}" => m
  }
}

resource "google_bigquery_dataset_iam_member" "members" {
  for_each = local.iam_member_map

  project    = google_bigquery_dataset.dataset.project
  dataset_id = google_bigquery_dataset.dataset.dataset_id
  role       = each.value.role
  member     = each.value.member
}