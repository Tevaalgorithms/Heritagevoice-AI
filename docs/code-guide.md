# Code guide

How the code is organised and the rules it follows, so you can find things and change them safely.

## Layers (dependencies point downward)

| Layer | Where | What lives here |
| --- | --- | --- |
| Interface | `frontend/`, `app/api/` | Streamlit pages and the FastAPI routes. No business rules. |
| Application | `app/uploads.py`, `app/review.py`, `app/ingest.py`, `app/indexing.py`, `app/revocation.py` | One use case per module: it checks access, calls repositories and adapters, and returns a result. |
| Workflows | `app/graph/`, `app/agents/` | LangGraph graphs and the model-backed steps. Authorization is passed in, never produced by a model. |
| Domain | `app/models/`, `app/security/` | Plain models and the access rules. No database or vendor code. |
| Ports and adapters | `app/ports.py`, `app/adapters/` | `ports.py` says what we need (speech, translation, vector search). Each adapter is one vendor behind it. `app/fakes.py` holds in-memory stand-ins for tests. |
| Data | `app/db/` | `tables.py` (SQLAlchemy tables), `repositories/` (one module per topic), `migrations/` (Alembic). Callers get domain models, never table rows. |

Rule of thumb: a module may import from a layer below it, never above. Routes and pages never
touch tables; use cases never import a vendor SDK; adapters never decide who may see what.

## Conventions

- **Small, named pieces.** Every function stays at complexity 5 or less (`ruff` C901, `xenon`
  rank A), with at most four arguments. When a function grows, split it or pass a small dataclass.
- **Every public class, module and package has a docstring** saying what it is for (`ruff` D100,
  D101, D104 enforce it). Say *why* in comments, not *what*.
- **Typed everywhere.** `mypy` is strict on `app/`. Use Pydantic models at the edges (API, files,
  model output) and frozen dataclasses for internal values.
- **Names:** repositories end in `Repository`, adapters name the vendor (`AmazonTranscribe`),
  request and response shapes end in `Request`/`Response`/`View`, and test stand-ins start with
  `Fake`.
- **Errors are values with safe codes.** Adapters raise `ProviderError(code=...)`; the API turns a
  code into a short message. Provider text, keys and personal data are never logged or returned.
- **Secrets stay out of code, Git, the database and logs.** Keys are read by name from Parameter
  Store at run time (`app/secrets.py`). `tests/test_no_secrets_in_repo.py` and gitleaks guard this.
- **Access is default-deny.** Unknown or restricted labels never reach retrieval, prompts or
  answers, and every search result is re-checked against PostgreSQL before it is shown.

## Where do I change...

| I want to... | Start here |
| --- | --- |
| Add or change an API route | `app/api/` (one module per area), then `UPDATE_SNAPSHOTS=1 uv run pytest tests/test_openapi_snapshot.py` |
| Add a database column | `app/db/tables.py`, a new file in `migrations/versions/`, the matching repository in `app/db/repositories/` |
| Add a spoken language | one line in `app/languages.py` (see `docs/runbooks/languages.md`) |
| Add a model, key or fall-back | the Settings page, no code (see `docs/runbooks/models.md`) |
| Add a vendor | a Protocol in `app/ports.py`, an adapter in `app/adapters/`, a fake in `app/fakes.py` |
| Change how the site looks | `frontend/static/theme.css` and `frontend/theme.py` |
| Change a deploy or AWS setting | `infra/` (Terraform, applied by the `infra` workflow) and `.github/workflows/` |

## Before you open a pull request

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy \
  && uv run xenon --max-absolute A --max-modules A --max-average A app ingestion frontend \
  && uv run pytest
```

Merging to `main` deploys automatically once CI passes, so review as if it were going live.
