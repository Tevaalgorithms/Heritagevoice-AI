output "deploy_role_arn" {
  description = "Store this as the GitHub environment variable AWS_DEPLOY_ROLE_ARN (not as a secret in Git)."
  value       = aws_iam_role.deploy.arn
}
