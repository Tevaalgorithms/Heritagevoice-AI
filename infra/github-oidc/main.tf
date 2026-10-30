# Roles that GitHub Actions assumes with short-lived credentials (OpenID Connect). No access keys
# are created or stored anywhere. This stack is applied by hand, never by CI, because it defines
# what CI may do:
#   - deploy: upload a release and run the deploy script on one instance (environment `demo`)
#   - terraform plan: read-only, for pull requests
#   - terraform apply: manage only heritagevoice-* resources (environment `infra`)
# The role names start with hv-ci-, outside the heritagevoice-* names CI may manage, so CI cannot
# change its own permissions.

data "aws_caller_identity" "current" {}

locals {
  oidc_url = "token.actions.githubusercontent.com"
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_oidc_provider ? 1 : 0
  url            = "https://${local.oidc_url}"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 0 : 1
  url   = "https://${local.oidc_url}"
}

locals {
  provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
}

data "aws_iam_policy_document" "trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_url}:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Only jobs that run in this repository's named environment (which requires approval).
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_url}:sub"
      values   = ["repo:${var.github_repo}:environment:${var.environment}"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name                 = "hv-ci-${var.environment}-deploy"
  assume_role_policy   = data.aws_iam_policy_document.trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "deploy" {
  statement {
    sid     = "RunDeployScriptOnTheInstance"
    actions = ["ssm:SendCommand"]
    resources = [
      "arn:aws:ec2:${var.region}:${data.aws_caller_identity.current.account_id}:instance/${var.instance_id}",
      "arn:aws:ssm:${var.region}::document/AWS-RunShellScript",
    ]
  }

  statement {
    sid       = "UploadReleases"
    actions   = ["s3:PutObject"]
    resources = ["arn:aws:s3:::${var.releases_bucket}/releases/*"]
  }

  statement {
    sid       = "ReadCommandResult"
    actions   = ["ssm:GetCommandInvocation", "ssm:ListCommandInvocations"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "deploy"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}


# --- Terraform from CI -----------------------------------------------------------------------

locals {
  repo_subject = "repo:${var.github_repo}"
  state_arn    = "arn:aws:s3:::${var.state_bucket}"
}

data "aws_iam_policy_document" "trust_plan" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_url}:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Pull requests (read-only plans) and runs on main.
    condition {
      test     = "StringLike"
      variable = "${local.oidc_url}:sub"
      values   = ["${local.repo_subject}:pull_request", "${local.repo_subject}:ref:refs/heads/main"]
    }
  }
}

data "aws_iam_policy_document" "trust_apply" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_url}:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Only jobs in the `infra` environment, which requires approval.
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_url}:sub"
      values   = ["${local.repo_subject}:environment:infra"]
    }
  }
}

resource "aws_iam_role" "terraform_plan" {
  name                 = "hv-ci-${var.environment}-terraform-plan"
  assume_role_policy   = data.aws_iam_policy_document.trust_plan.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy_attachment" "plan_read_only" {
  role       = aws_iam_role.terraform_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

data "aws_iam_policy_document" "plan_state" {
  statement {
    sid       = "ReadState"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [local.state_arn, "${local.state_arn}/*"]
  }
}

resource "aws_iam_role_policy" "plan_state" {
  name   = "read-state"
  role   = aws_iam_role.terraform_plan.id
  policy = data.aws_iam_policy_document.plan_state.json
}

resource "aws_iam_role" "terraform_apply" {
  name                 = "hv-ci-${var.environment}-terraform-apply"
  assume_role_policy   = data.aws_iam_policy_document.trust_apply.json
  max_session_duration = 3600
}

# Everything except IAM, Organizations and account settings; IAM is added back below, scoped.
resource "aws_iam_role_policy_attachment" "apply_power_user" {
  role       = aws_iam_role.terraform_apply.name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

data "aws_iam_policy_document" "apply_iam" {
  statement {
    sid = "ManageHeritageVoiceRoles"
    actions = [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:GetRole",
      "iam:UpdateRole",
      "iam:UpdateAssumeRolePolicy",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:ListRoleTags",
      "iam:PutRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:GetRolePolicy",
      "iam:ListRolePolicies",
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:ListInstanceProfilesForRole",
      "iam:PassRole",
    ]
    resources = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/heritagevoice-*"]
  }

  statement {
    sid = "ManageHeritageVoiceInstanceProfiles"
    actions = [
      "iam:CreateInstanceProfile",
      "iam:DeleteInstanceProfile",
      "iam:GetInstanceProfile",
      "iam:AddRoleToInstanceProfile",
      "iam:RemoveRoleFromInstanceProfile",
      "iam:TagInstanceProfile",
      "iam:UntagInstanceProfile",
    ]
    resources = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/heritagevoice-*"]
  }
}

resource "aws_iam_role_policy" "apply_iam" {
  name   = "manage-heritagevoice-iam"
  role   = aws_iam_role.terraform_apply.id
  policy = data.aws_iam_policy_document.apply_iam.json
}
