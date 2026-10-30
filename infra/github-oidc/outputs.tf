output "terraform_plan_role_arn" {
  description = "Repository variable AWS_TF_PLAN_ROLE_ARN (read-only plans on pull requests)."
  value       = aws_iam_role.terraform_plan.arn
}

output "terraform_apply_role_arn" {
  description = "Environment `infra` variable AWS_TF_APPLY_ROLE_ARN (applies, after approval)."
  value       = aws_iam_role.terraform_apply.arn
}

output "deploy_role_arn" {
  description = "Store this as the GitHub environment variable AWS_DEPLOY_ROLE_ARN (not as a secret in Git)."
  value       = aws_iam_role.deploy.arn
}
