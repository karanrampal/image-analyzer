variable "project_id" {
  description = "The Google Cloud project ID"
  type        = string
}

variable "dataset_id" {
  description = "The ID of the dataset"
  type        = string
}

variable "location" {
  description = "The regional location for the dataset"
  type        = string
  default     = "US"
}

variable "friendly_name" {
  description = "A friendly name for the dataset"
  type        = string
  default     = null
}

variable "description" {
  description = "Description of the dataset"
  type        = string
  default     = null
}

variable "delete_contents_on_destroy" {
  description = "If set to true, delete all the tables in the dataset when destroying the resource"
  type        = bool
  default     = false
}

variable "labels" {
  description = "Labels to apply to the dataset"
  type        = map(string)
  default     = {}
}

variable "iam_members" {
  description = "List of IAM members to grant access to the dataset"
  type = list(object({
    role   = string
    member = string
  }))
  default = []
}