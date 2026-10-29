# Infrastructure

Terraform for the AWS resources. Never commit state, plans or `*.tfvars` (see `AGENTS.md`); use a
remote encrypted backend and keep variable values in a local, ignored `*.tfvars` file.

- `cognito/`: user pool, `member` / `reviewer` / `admin` groups, UI app client, hosted domain.

> Status: written but **not yet validated or applied**. Run `terraform init && terraform validate`
> before first use, and review `terraform plan` locally; do not paste plan output anywhere.
