# Contributing

1. Run `scripts/install-hooks.sh` once per clone to enable the secret-scanning commit hook (needs gitleaks or Docker).
2. Never commit `.env`, Terraform state or plans, `*.tfvars`, keys, or restricted recordings. Do not use `--no-verify`.
3. Before opening a pull request: `uv run ruff check . && uv run ruff format --check . && uv run pytest`.

See [`AGENTS.md`](AGENTS.md) and [`SECURITY.md`](SECURITY.md).
