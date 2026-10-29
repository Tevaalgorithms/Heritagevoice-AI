variable "region" {
  type        = string
  description = "AWS region for the user pool (same region as the application)."
}

variable "environment" {
  type        = string
  description = "dev, staging or demo. One pool per environment."
}

variable "domain_prefix" {
  type        = string
  description = "Globally unique prefix for the hosted sign-in domain."
}

variable "callback_urls" {
  type        = list(string)
  description = "Exact HTTPS callback URLs of the UI (Streamlit's /oauth2callback)."
}

variable "logout_urls" {
  type        = list(string)
  description = "Exact HTTPS URLs the user returns to after signing out."
}
