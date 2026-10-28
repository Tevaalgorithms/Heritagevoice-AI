# AGENTS.md

Instructions for AI coding agents (and humans) working in this repository.

## Security rules (never break these)

1. **Never commit secrets.** That includes API keys (LangSmith, LLM providers, AWS), tokens, passwords, private keys,
   database URLs with passwords, and anything from `.env`.
2. **Never commit Terraform state or plans.** `*.tfstate*`, `tfplan`, `*.tfplan`, `*.tfvars` and `.terraform/` stay
   local. Do not paste `terraform plan` output, or `terraform show -json`, into files, issues, PRs or commit messages:
   plans contain secret values. Use a remote encrypted backend for state.
3. **Never read, print or echo `.env` or secret files** into the conversation or logs. `.env.example` lists names only,
   with empty values. New settings go in `.env.example` with no value.
4. **Never bypass the hook.** Do not use `git commit --no-verify`, edit `core.hooksPath`, or weaken `.githooks/pre-commit`,
   `.gitleaks.toml` or the CI `secrets` job to get a commit through. If the hook blocks you, remove the secret.
5. **No restricted recordings or community data in Git.** `data/` contents (except `.gitkeep` and `README.md`) are ignored.
   Do not put secrets or restricted material into prompts, logs or LangSmith trace metadata.
6. **If a secret is ever committed or pushed**, treat it as exposed: rotate it first, then remove it from history.

## Setup (once per clone)

```bash
scripts/install-hooks.sh     # turns on .githooks/pre-commit
brew install gitleaks        # or keep Docker running; the hook uses either
```

The pre-commit hook blocks forbidden file names, Terraform plan output, and anything gitleaks detects in staged changes.
CI re-scans the full history on every push and PR (`secrets` job); require it in branch protection, since hooks can be skipped.

## Checks before finishing a change

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

`tests/test_no_secrets_in_repo.py` fails if a credential-shaped string or an unignored secret file pattern is added.

## Project notes

- Default-deny access: unknown or restricted labels must never reach retrieval, prompts or answers.
- Tracing is off by default (`LANGSMITH_TRACING=false`); keep inputs/outputs hidden until redaction is in place.
- Keep dependencies locked: change `pyproject.toml`, run `uv lock`, and regenerate `requirements.txt`.
