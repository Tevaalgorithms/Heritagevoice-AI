variable "region" {
  type        = string
  description = "AWS region for the user pool (same region as the application)."
}

variable "environment" {
  type        = string
  description = "dev, staging or prod. One pool per environment."
}

variable "domain_prefix" {
  type        = string
  description = "Globally unique prefix for the hosted sign-in domain."
}

variable "login_domain" {
  type        = string
  default     = ""
  description = "Optional custom sign-in domain, for example login.heritagevoice.org. When set, the hosted sign-in and sign-up pages use it instead of the Amazon-owned domain. Needs route53_zone_name."
}

variable "route53_zone_name" {
  type        = string
  default     = ""
  description = "Public Route 53 zone that holds login_domain (for example heritagevoice.org). The zone's top-level name must already have an A record, which Cognito checks."
}

variable "callback_urls" {
  type        = list(string)
  description = "Exact HTTPS callback URLs of the UI (Streamlit's /oauth2callback)."
}

variable "logout_urls" {
  type        = list(string)
  description = "Exact HTTPS URLs the user returns to after signing out."
}
