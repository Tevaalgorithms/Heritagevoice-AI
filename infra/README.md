# Infrastructure

Terraform for the AWS resources. Never commit state, plans or `*.tfvars` (see `AGENTS.md`); use a
remote encrypted backend and keep variable values in a local, ignored `*.tfvars` file.

- `cognito/`: user pool, `member` / `reviewer` / `admin` groups, UI app client, hosted domain.
- `github-oidc/`: the IAM role GitHub Actions assumes (OpenID Connect, no keys) to deploy to the instance through Systems Manager. Used by `.github/workflows/deploy.yml`.
- `single-instance/`: the low-cost MVP profile: one instance, encrypted data disk with daily snapshots, KMS-encrypted private audio bucket, instance role, budget alert. See [`docs/runbooks/deploy-single-instance.md`](../docs/runbooks/deploy-single-instance.md).

> All three stacks pass `terraform fmt` and `terraform validate` (checked in CI). Applies run only
> through the `infra` workflow after a maintainer approves the `infra` environment (see
> [`docs/runbooks/repository-settings.md`](../docs/runbooks/repository-settings.md)); the
> `github-oidc` stack is applied by hand because it defines what CI may do. Do not paste plan output
> anywhere: it can contain secret values.
