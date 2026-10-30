variable "region" {
  type        = string
  description = "AWS region of the instance."
}

variable "environment" {
  type        = string
  description = "Must match the GitHub environment name that is allowed to deploy (for example prod)."
}

variable "github_subject_prefix" {
  type        = string
  default     = ""
  description = "Subject prefix GitHub puts in its tokens, e.g. repo:owner@123/name@456. Get it with: gh api repos/<owner>/<repo>/actions/oidc/customization/sub --jq .sub_claim_prefix. Empty uses repo:<github_repo>."
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
