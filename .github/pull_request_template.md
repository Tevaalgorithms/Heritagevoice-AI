## What and why

<!-- One or two sentences. Link the issue this closes. -->

## Checklist

- [ ] Complexity: every changed function is cyclomatic complexity <= 5 (`ruff` and `xenon` pass)
- [ ] Tests: new or changed behaviour has tests, including the failing/denied case for any access rule
- [ ] Types: `uv run mypy` passes
- [ ] No secrets: no keys, tokens, passwords, `.env`, Terraform state or plans in the diff
- [ ] No restricted data: no recordings, community material or private transcripts in code, fixtures, logs or traces
- [ ] Permissions: authorization still comes from the server-side `Principal`, never from model output or client input
- [ ] Dependencies: if `pyproject.toml` changed, `uv lock` was run and `requirements.txt` regenerated
- [ ] Infra or workflow changes (`infra/`, `.github/`, `deploy/`): explained above, and nothing here can reach AWS without a maintainer's approval
