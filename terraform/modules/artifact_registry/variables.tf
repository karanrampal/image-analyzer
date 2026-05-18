variable "project_id" {
  description = "The Google Cloud project ID"
  type        = string
}

variable "location" {
  description = "The location for the Artifact Registry repository"
  type        = string
}

variable "repository_id" {
  description = "The ID of the repository"
  type        = string
}

variable "description" {
  description = "Description of the repository"
  type        = string
  default     = "Docker repository"
}

variable "format" {
  description = "The format of the repository"
  type        = string
  default     = "DOCKER"
}

variable "cleanup_policies" {
  description = "List of cleanup policies for the repository. Each policy may use a 'condition' block (filter by age, tag state, version prefix, etc.) or a 'most_recent_versions' block (keep the N newest versions). Both are optional but at least one must be set per policy."
  type = list(object({
    id     = string
    action = string
    condition = optional(object({
      tag_state             = optional(string)
      tag_prefixes          = optional(list(string))
      version_name_prefixes = optional(list(string))
      package_name_prefixes = optional(list(string))
      older_than            = optional(string)
      newer_than            = optional(string)
    }))
    most_recent_versions = optional(object({
      package_name_prefixes = optional(list(string))
      keep_count            = optional(number)
    }))
  }))
  default = [
    {
      id     = "delete-old-versions"
      action = "DELETE"
      condition = {
        older_than = "90d"
      }
    }
  ]
}

variable "labels" {
  description = "Default labels to apply to the repository"
  type        = map(string)
  default     = {}
}

variable "iam_members" {
  description = "List of IAM role-member pairs for the repository (stable composite keys used internally)."
  type = list(object({
    role   = string
    member = string
  }))
  default = []
}
