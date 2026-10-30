variable "region" {
  type        = string
  description = "AWS region of the instance."
}

variable "environment" {
  type        = string
  description = "Must match the GitHub environment name that is allowed to deploy (for example demo)."
}

variable "github_repo" {
  type        = string
  description = "owner/name of the repository allowed to deploy."
}

variable "instance_id" {
  type        = string
  description = "ID of the instance to deploy to (output of infra/single-instance)."
}

variable "releases_bucket" {
  type        = string
  description = "Name of the private releases bucket (output of infra/single-instance)."
}

variable "state_bucket" {
  type        = string
  description = "Name of the Terraform state bucket (the CI roles read it for plans)."
}

variable "create_oidc_provider" {
  type        = bool
  default     = true
  description = "Set to false if the account already has the GitHub OIDC provider (only one is allowed)."
}
