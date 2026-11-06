# Amazon Cognito: one user pool per environment with three role groups.
# Roles are enforced by the application; Cognito proves who the user is (see
# docs/runbooks/setup.md). Users are never defined here: admins are invited, not scripted.

locals {
  roles = toset(["member", "reviewer", "admin"])
}

resource "aws_cognito_user_pool" "this" {
  name                     = "heritagevoice-${var.environment}"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  mfa_configuration        = "ON"
  deletion_protection      = "ACTIVE"

  software_token_mfa_configuration {
    enabled = true
  }

  admin_create_user_config {
    # Anyone may create an account (email verified, MFA on), but the app denies every request
    # from an account until an admin approves it: see docs/runbooks/accounts.md.
    allow_admin_create_user_only = false
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 3
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
}

resource "aws_cognito_user_group" "role" {
  for_each     = local.roles
  name         = each.key
  user_pool_id = aws_cognito_user_pool.this.id
  description  = "HeritageVoice ${each.key} role"
}

resource "aws_cognito_user_pool_client" "ui" {
  name         = "heritagevoice-ui-${var.environment}"
  user_pool_id = aws_cognito_user_pool.this.id

  generate_secret                      = true # Streamlit is a server-side (confidential) client
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = var.callback_urls
  logout_urls                          = var.logout_urls
  explicit_auth_flows                  = ["ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors        = "ENABLED"

  access_token_validity  = 30
  id_token_validity      = 30
  refresh_token_validity = 1

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}

locals {
  custom_domain = var.login_domain != "" && var.route53_zone_name != ""
}

# One domain per pool: Amazon's own (<prefix>.auth.<region>.amazoncognito.com) until `login_domain`
# is set, then the custom one. Changing it replaces the domain, so sign-in is down for a few minutes.
resource "aws_cognito_user_pool_domain" "this" {
  domain          = local.custom_domain ? var.login_domain : var.domain_prefix
  user_pool_id    = aws_cognito_user_pool.this.id
  certificate_arn = local.custom_domain ? aws_acm_certificate_validation.login[0].certificate_arn : null
}

data "aws_route53_zone" "login" {
  count        = local.custom_domain ? 1 : 0
  name         = var.route53_zone_name
  private_zone = false
}

# The certificate for the custom sign-in domain, proved by a DNS record in our own zone.
resource "aws_acm_certificate" "login" {
  count             = local.custom_domain ? 1 : 0
  provider          = aws.us_east_1
  domain_name       = var.login_domain
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "login_validation" {
  for_each = local.custom_domain ? {
    for option in aws_acm_certificate.login[0].domain_validation_options : option.domain_name => option
  } : {}

  zone_id         = data.aws_route53_zone.login[0].zone_id
  name            = each.value.resource_record_name
  type            = each.value.resource_record_type
  records         = [each.value.resource_record_value]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "login" {
  count                   = local.custom_domain ? 1 : 0
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.login[0].arn
  validation_record_fqdns = [for record in aws_route53_record.login_validation : record.fqdn]
}

# Cognito serves the custom domain through its own CloudFront distribution; point the name at it.
resource "aws_route53_record" "login" {
  count   = local.custom_domain ? 1 : 0
  zone_id = data.aws_route53_zone.login[0].zone_id
  name    = var.login_domain
  type    = "A"

  alias {
    name                   = aws_cognito_user_pool_domain.this.cloudfront_distribution
    zone_id                = aws_cognito_user_pool_domain.this.cloudfront_distribution_zone_id
    evaluate_target_health = false
  }
}

# The hosted sign-in page, styled like the app. The logo must be under 100 KB and the stylesheet
# under 3 KB. Omitting `client_id` applies it to every app client in the pool. It needs the domain
# to exist first.
resource "aws_cognito_user_pool_ui_customization" "branding" {
  user_pool_id = aws_cognito_user_pool.this.id
  css          = file("${path.module}/branding/hosted-ui.css")
  image_file   = filebase64("${path.module}/branding/logo.png")

  depends_on = [aws_cognito_user_pool_domain.this]

  # Apply it again whenever the domain is replaced.
  lifecycle {
    replace_triggered_by = [aws_cognito_user_pool_domain.this]
  }
}
