# Contributing

Thank you for helping. This project handles people's voices and cultural knowledge, so the rules
below are about care as much as code. By taking part you agree to the
[Code of Conduct](CODE_OF_CONDUCT.md). Contributions are licensed under the
[Apache License 2.0](LICENSE).

## Before you start

- **Small fixes** (typos, docs, clear bugs): open a pull request directly.
- **Anything larger** (a feature, a new dependency, a change to access or consent rules): open an
  issue first so a maintainer can agree the approach.
- **Security problems:** do **not** open an issue. Follow [SECURITY.md](SECURITY.md).
- **Never** include real recordings, transcripts, community material, keys or personal data in
  code, tests, issues or pull requests. Use synthetic fixtures only.

## Set up

```sh
uv sync --locked
scripts/install-hooks.sh       # enables the secret-scanning commit hook (needs gitleaks or Docker)
cp .env.example .env           # never commit .env
```

See [`docs/runbooks/setup.md`](docs/runbooks/setup.md) to run the API, worker and interface, and the
[code guide](docs/code-guide.md) for how the code is organised.

## Standards

Run all of these before opening a pull request; CI runs them too.

```sh
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run xenon --max-absolute A --max-modules A --max-average A app ingestion frontend
uv run pytest
```

- Cyclomatic complexity of at most 5 per function, at most 4 arguments, strict typing, and a
  docstring on every public class, module and package. Match the style of the code around you.
- New or changed behaviour needs tests, **including the denied case** for any access rule.
- Authorization comes only from the server-side principal, never from request data or model output.
- Default-deny: unknown or restricted labels must never reach search, prompts or answers.
- Dependencies are locked. Change `pyproject.toml`, then run `uv lock` and regenerate
  `requirements.txt` (`uv export --locked --no-header --no-dev --format requirements-txt --output-file requirements.txt`).
- Do not use `git commit --no-verify` and do not weaken the hook, `.gitleaks.toml` or the CI
  `secrets` job. If a secret is ever committed, treat it as exposed: rotate it first.
- No secrets, Terraform state or plans, `*.tfvars`, or account identifiers in the repository.

## Pull requests

1. Fork the repository and create a branch from `main`.
2. Keep each pull request focused on one change. Fill in the pull request template.
3. CI must pass. Pull requests from forks run without any cloud credentials.
4. **A maintainer must approve every pull request before it is merged** (the code owners listed in
   [`.github/CODEOWNERS`](.github/CODEOWNERS)). Changes to `infra/`, `.github/` or `deploy/` get extra
   scrutiny because they decide what runs against production.
5. Merging to `main` does not deploy by itself: a maintainer approves each deployment separately.

Maintainers: the repository settings that enforce this are described in
[`docs/runbooks/repository-settings.md`](docs/runbooks/repository-settings.md).

See also [`AGENTS.md`](AGENTS.md), which applies the same rules to AI coding agents.
