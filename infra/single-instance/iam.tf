# The instance role replaces long-lived access keys: the app gets short-lived credentials.

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "instance" {
  name               = "heritagevoice-${var.environment}-instance"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

# Session Manager: shell access without opening SSH.
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

locals {
  ssm_path      = "/heritagevoice/${var.environment}"
  user_pool_arn = "arn:aws:cognito-idp:${var.region}:${data.aws_caller_identity.current.account_id}:userpool/${var.cognito_user_pool_id}"
  # Names are matched as IAM wildcards. `*_API_KEY` lets a catalogue model use its own key.
  writable_parameters = ["*_API_KEY", "PINECONE_*", "EMBEDDING_*", "LANGSMITH_*", "NEO4J_*"]
  ssm_parameter_arn   = "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter${local.ssm_path}"
}

data "aws_iam_policy_document" "app" {
  statement {
    sid       = "AudioObjects"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.audio.arn}/*"]
  }

  statement {
    sid       = "AudioBucket"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.audio.arn]
  }

  statement {
    sid       = "ReleaseObjects"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.releases.arn}/releases/*"]
  }

  statement {
    sid       = "EncryptionKey"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey", "kms:Encrypt", "kms:DescribeKey"]
    resources = [aws_kms_key.app.arn]
  }

  statement {
    sid = "SpeechToText"
    actions = [
      "transcribe:StartTranscriptionJob",
      "transcribe:GetTranscriptionJob",
      "transcribe:DeleteTranscriptionJob",
    ]
    resources = ["*"] # Transcribe job names are not known in advance
  }

  statement {
    sid       = "ReadOwnSecrets"
    actions   = ["ssm:GetParametersByPath", "ssm:GetParameters", "ssm:GetParameter"]
    resources = [local.ssm_parameter_arn, "${local.ssm_parameter_arn}/*"]
  }

  # The admin portal saves API keys and service settings here. Only these names can be written:
  # never the database password, the cookie secret or the sign-in secret.
  statement {
    sid       = "WriteIntegrationSettings"
    actions   = ["ssm:PutParameter"]
    resources = [for name in local.writable_parameters : "${local.ssm_parameter_arn}/${name}"]
  }

  statement {
    sid = "ManageUsers"
    actions = [
      "cognito-idp:AdminCreateUser",
      "cognito-idp:AdminAddUserToGroup",
      "cognito-idp:AdminRemoveUserFromGroup",
      "cognito-idp:AdminListGroupsForUser",
      "cognito-idp:AdminDisableUser",
      "cognito-idp:AdminUserGlobalSignOut",
      "cognito-idp:ListUsers",
    ]
    resources = [local.user_pool_arn]
  }
}

resource "aws_iam_role_policy" "app" {
  name   = "app"
  role   = aws_iam_role.instance.id
  policy = data.aws_iam_policy_document.app.json
}

resource "aws_iam_instance_profile" "instance" {
  name = "heritagevoice-${var.environment}-instance"
  role = aws_iam_role.instance.name
}
