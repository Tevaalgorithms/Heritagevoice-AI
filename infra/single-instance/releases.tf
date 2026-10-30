# Private bucket for release tarballs. CI uploads; the instance role reads. Nothing is public.

resource "aws_s3_bucket" "releases" {
  bucket = "heritagevoice-${var.environment}-releases-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "releases" {
  bucket                  = aws_s3_bucket.releases.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "releases" {
  bucket = aws_s3_bucket.releases.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "releases" {
  bucket = aws_s3_bucket.releases.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "releases" {
  bucket = aws_s3_bucket.releases.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "releases" {
  bucket = aws_s3_bucket.releases.id

  rule {
    id     = "expire-old-releases"
    status = "Enabled"

    filter {
      prefix = "releases/"
    }

    expiration {
      days = 90
    }

    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }
}

data "aws_iam_policy_document" "releases_bucket" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.releases.arn, "${aws_s3_bucket.releases.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "releases" {
  bucket     = aws_s3_bucket.releases.id
  policy     = data.aws_iam_policy_document.releases_bucket.json
  depends_on = [aws_s3_bucket_public_access_block.releases]
}
