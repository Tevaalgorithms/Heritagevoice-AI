# Infrastructure

Terraform for the AWS resources. Never commit state, plans or `*.tfvars` (see `AGENTS.md`); use a
remote encrypted backend and keep variable values in a local, ignored `*.tfvars` file.

- `cognito/`: user pool, `member` / `reviewer` / `admin` groups, UI app client, hosted domain.
- `github-oidc/`: the IAM role GitHub Actions assumes (OpenID Connect, no keys) to deploy to the instance through Systems Manager. Used by `.github/workflows/deploy.yml`.
- `single-instance/`: the low-cost MVP profile: one instance, encrypted data disk with daily snapshots, KMS-encrypted private audio bucket, instance role, budget alert. See [`docs/runbooks/deploy-single-instance.md`](../docs/runbooks/deploy-single-instance.md).

> Status: all three stacks pass `terraform fmt` and `terraform validate` (also checked in CI) but have
> **not been applied** to a real AWS account. Review `terraform plan` locally before applying; do
> not paste plan output anywhere.
