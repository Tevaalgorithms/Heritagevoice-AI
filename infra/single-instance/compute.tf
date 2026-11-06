data "aws_ssm_parameter" "al2023_arm64" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

resource "aws_ebs_volume" "data" {
  availability_zone = aws_subnet.public.availability_zone
  size              = var.data_volume_gb
  type              = "gp3"
  encrypted         = true
  kms_key_id        = aws_kms_key.app.arn
  tags              = { Name = "heritagevoice-${var.environment}-data", Backup = "daily" }
}

resource "aws_instance" "app" {
  ami                    = data.aws_ssm_parameter.al2023_arm64.value
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.web.id]
  iam_instance_profile   = aws_iam_instance_profile.instance.name

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
    encrypted   = true
  }

  # IMDSv2 only. Hop limit 2 lets the containers on this host reach the role credentials.
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    hv_deploy_script      = file("${path.module}/../../deploy/hv-deploy.sh")
    releases_bucket       = aws_s3_bucket.releases.bucket
    data_volume_id        = replace(aws_ebs_volume.data.id, "-", "")
    domain                = var.domain
    region                = var.region
    audio_bucket          = aws_s3_bucket.audio.bucket
    kms_key_arn           = aws_kms_key.app.arn
    cognito_user_pool_id  = var.cognito_user_pool_id
    cognito_app_client_id = var.cognito_app_client_id
    ssm_path              = local.ssm_path
  })
  user_data_replace_on_change = false # change settings through deploy/start.sh, not by replacing the host

  tags = { Name = "heritagevoice-${var.environment}", Backup = "daily" }

  lifecycle {
    # Never replace the host (and its data) because a newer AMI exists or the first-boot script
    # changed. Settings are changed through deploys, not by rebuilding the instance.
    ignore_changes = [ami, user_data]
  }
}

resource "aws_volume_attachment" "data" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.data.id
  instance_id = aws_instance.app.id
}

resource "aws_eip" "app" {
  domain   = "vpc"
  instance = aws_instance.app.id
  tags     = { Name = "heritagevoice-${var.environment}" }

  depends_on = [aws_internet_gateway.this]
}

data "aws_route53_zone" "this" {
  count        = var.route53_zone_name == "" ? 0 : 1
  name         = var.route53_zone_name
  private_zone = false
}

resource "aws_route53_record" "app" {
  count   = var.route53_zone_name == "" ? 0 : 1
  zone_id = data.aws_route53_zone.this[0].zone_id
  name    = var.domain
  type    = "A"
  ttl     = 300
  records = [aws_eip.app.public_ip]
}

# When the site lives at the top of its own domain (heritagevoice.org), `www.` points at the same
# server too; Caddy then redirects it to the main address. A subdomain gets no `www.` record.
resource "aws_route53_record" "www" {
  count   = var.route53_zone_name != "" && var.route53_zone_name == var.domain ? 1 : 0
  zone_id = data.aws_route53_zone.this[0].zone_id
  name    = "www.${var.domain}"
  type    = "A"
  ttl     = 300
  records = [aws_eip.app.public_ip]
}

# Daily snapshots of the root and data disks (tag Backup=daily), keeping the last 7.
data "aws_iam_policy_document" "dlm_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["dlm.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "dlm" {
  name               = "heritagevoice-${var.environment}-dlm"
  assume_role_policy = data.aws_iam_policy_document.dlm_assume.json
}

resource "aws_iam_role_policy_attachment" "dlm" {
  role       = aws_iam_role.dlm.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSDataLifecycleManagerServiceRole"
}

resource "aws_dlm_lifecycle_policy" "daily" {
  description        = "HeritageVoice ${var.environment} daily snapshots"
  execution_role_arn = aws_iam_role.dlm.arn
  state              = "ENABLED"

  policy_details {
    resource_types = ["VOLUME"]
    target_tags    = { Backup = "daily" }

    schedule {
      name = "daily-7-days"

      create_rule {
        interval      = 24
        interval_unit = "HOURS"
        times         = ["03:00"]
      }

      retain_rule {
        count = 7
      }

      copy_tags = true
    }
  }
}

resource "aws_budgets_budget" "monthly" {
  count        = var.budget_email == "" ? 0 : 1
  name         = "heritagevoice-${var.environment}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }
}
