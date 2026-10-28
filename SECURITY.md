# Security

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's **private vulnerability reporting**
(Security tab → Report a vulnerability) on this repository. Include what you found, how to reproduce it, and
the version or commit. Say if the report involves real credentials, so they can be rotated first.

## Secrets: what is and is not in this repository

- No credentials are committed. Local settings live in a git-ignored `.env`. `.env.example` lists names only, with empty values.
- Terraform state (`*.tfstate*`), plans (`tfplan`, `*.tfplan`), `*.tfvars`, and key files are git-ignored.
  Terraform state and plans contain secret values: keep state in an encrypted remote backend, and never paste plan output into Git.
- Restricted recordings and community data under `data/` are git-ignored.
- If a secret is ever committed, treat it as exposed: rotate it first ([`docs/runbooks/secrets.md`](docs/runbooks/secrets.md)),
  then remove it from history.

## Stopping secrets from reaching GitHub

1. **Commit hook (per clone).** Run `scripts/install-hooks.sh` once. Every commit is scanned with gitleaks and blocked if it
   contains a secret, a file such as `.env`, `*.tfvars`, `*.tfstate`, `tfplan`, `*.pem` or `*.key`, or Terraform plan output.
2. **CI.** Every push and pull request runs gitleaks over the whole history (`secrets` job in `.github/workflows/ci.yml`).
3. **`.gitignore`.** Local settings, Terraform state and plans, key files and restricted data are ignored.
4. **Tests.** `tests/test_no_secrets_in_repo.py` fails on credential-shaped strings.

Hooks can be skipped with `--no-verify`, so treat layer 2 as the real guarantee: set a branch protection rule requiring
the `secrets` check before merging.
