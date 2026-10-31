variable "region" {
  type        = string
  description = "AWS region. Use the same region as the Cognito user pool."
}

variable "environment" {
  type        = string
  description = "dev, staging or prod. One stack per environment."
}

variable "domain" {
  type        = string
  description = "Public host name for the HTTPS site (its A record must point at the instance's IP)."
}

variable "route53_zone_name" {
  type        = string
  default     = ""
  description = "Optional name of an existing public Route 53 zone (for example example.org). If set, Terraform adds only the A record for the domain to it."
}

variable "instance_type" {
  type        = string
  default     = "t4g.small"
  description = "Arm (Graviton) instance size. t4g.small is enough for the MVP demo."
}

variable "data_volume_gb" {
  type        = number
  default     = 20
  description = "Size of the encrypted data disk (PostgreSQL data and certificates)."
}

variable "cognito_user_pool_id" {
  type        = string
  description = "ID of the Cognito user pool (output of infra/cognito)."
}

variable "cognito_app_client_id" {
  type        = string
  description = "ID of the Cognito app client (output of infra/cognito)."
}

variable "budget_limit_usd" {
  type        = number
  default     = 40
  description = "Monthly budget; an email is sent at 80% of actual and 100% of forecast spend."
}

variable "budget_email" {
  type        = string
  default     = ""
  description = "Where budget alerts go. Leave empty to skip the budget alert."
}
