# Local setup: web app, API and worker

Start all three processes from a clean clone. Nothing here needs a real API key: the API,
worker and UI run against a local PostgreSQL, and the AI parts are still fakes (see
`uv run python -m app.skeleton`).

## Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Docker (for the local PostgreSQL) and, once, `scripts/install-hooks.sh` plus gitleaks
  (see `AGENTS.md`)

## 1. Install

```sh
uv sync --locked
cp .env.example .env        # first setup only; never overwrite an existing .env
```

Edit `.env` (it is git-ignored and must never be committed):

| Variable | Value |
| --- | --- |
| `HERITAGEVOICE_DEV_API_TOKEN` | a long random string, local use only (`python -c "import secrets; print(secrets.token_hex(24))"`) |
| `POSTGRES_PASSWORD` | a long random string |
| `NEO4J_PASSWORD` | any string for now (Neo4j is not used until the graph work) |
| `HERITAGEVOICE_DATABASE_URL` | `postgresql+psycopg://heritagevoice:<POSTGRES_PASSWORD>@127.0.0.1:5432/heritagevoice?connect_timeout=5` |

## 2. Start PostgreSQL and create the tables

```sh
docker compose --profile infrastructure up -d postgres
uv run alembic upgrade head
```

If port 5432 is already in use by another database, stop that one or change the host port in
`docker-compose.yml` and in the URL above.

## 3. Start the three processes (three terminals)

```sh
uv run uvicorn app.api.main:app --reload --host 127.0.0.1                     # API
uv run python -m app.worker                                                   # worker
uv run python -m streamlit run frontend/streamlit_app.py --server.address 127.0.0.1   # UI
```

## 4. Check it works

```sh
curl -i http://127.0.0.1:8000/health      # 200, process is alive
curl -i http://127.0.0.1:8000/ready       # 200 when PostgreSQL is reachable, otherwise 503
```

- Every response carries an `X-Trace-ID` header; the same ID appears in the API logs.
- `/ready` lists each configured dependency (`ok`, `failed`, `not_configured` or `skipped`).
  Unconfigured optional services (for example the audio bucket) are skipped, not failed.
- The UI is at <http://127.0.0.1:8501>; the sidebar shows the API status. Upload and Review are
  placeholders until segments 03 and 04. `/query` stays closed (503) until the agents are built.

## 5. Checks before opening a pull request

```sh
uv run ruff check . && uv run ruff format --check . && uv run mypy \
  && uv run xenon --max-absolute A --max-modules A --max-average A app ingestion frontend \
  && uv run pytest
```

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| `/ready` returns 503 with `postgres: not_configured` | `HERITAGEVOICE_DATABASE_URL` is not set in `.env` |
| `/ready` returns 503 with `postgres: failed` | database not running, wrong password, or wrong port |
| `password authentication failed` | the URL is reaching a different PostgreSQL than the compose one (check the port) |
| Worker marks jobs `failed` with `no_handler` | expected until the transcription and indexing handlers exist |
| UI sidebar says the API is unavailable | the API is not running on `HERITAGEVOICE_API_URL` |
