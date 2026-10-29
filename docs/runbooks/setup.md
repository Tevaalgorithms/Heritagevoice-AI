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

## Uploading and transcribing a recording

1. For local development set `HERITAGEVOICE_AUDIO_LOCAL_DIR` to a folder inside `data/` (it is
   git-ignored) and `HERITAGEVOICE_ASR_PROVIDER=fake`, which makes the worker produce a short
   canned draft instead of calling a speech service. The fake is refused outside the local
   environment.
2. An upload needs a **consent record** for the community. There is no endpoint for creating
   consents yet; until one exists, insert one with a script (see `tests/helpers.py::consent`).
3. Upload in the UI (Upload page) or with curl; the same `Idempotency-Key` returns the same result:

   ```sh
   curl -X POST http://127.0.0.1:8000/v1/recordings \
     -H "Authorization: Bearer $HERITAGEVOICE_DEV_API_TOKEN" -H "Idempotency-Key: my-key-0001" \
     -F language=ta -F community_id=dev -F consent_id=consent-1 -F file=@recording.wav
   ```

4. Run the worker (`uv run python -m app.worker`); poll `GET /v1/jobs/{job_id}`. A finished job
   is `review`: the draft transcript is visible at `GET /v1/recordings/{id}` but stays out of
   search until a reviewer approves it (segment 04).

Deployed, the worker uses Amazon Transcribe (Tamil `ta-IN`, English `en-US`) on the audio already
in the private bucket; set `HERITAGEVOICE_AWS_REGION` (the region comes from settings, not from the
machine's AWS config). Its IAM role needs `transcribe:StartTranscriptionJob`,
`GetTranscriptionJob` and `DeleteTranscriptionJob`, read and write on the bucket, and use of the
KMS key. Provider failures are retried up to three times, then the job fails with a safe code
(`asr`). Consent withdrawn after upload fails the job at once with `consent`.

## Sign-in and roles (Amazon Cognito)

Local runs need none of this: with `HERITAGEVOICE_ENVIRONMENT=local` the dev token signs you in
as a member of a `dev` community (`HERITAGEVOICE_DEV_ROLE` picks member, reviewer or admin).
In any other environment only Cognito access tokens are accepted.

1. Create the user pool with `infra/cognito/` (see `infra/README.md`), then set
   `HERITAGEVOICE_COGNITO_REGION`, `HERITAGEVOICE_COGNITO_USER_POOL_ID` and
   `HERITAGEVOICE_COGNITO_APP_CLIENT_ID` and `HERITAGEVOICE_ENVIRONMENT=production` (or staging).
2. UI sign-in uses Streamlit's built-in OIDC login. Put this in `.streamlit/secrets.toml`
   (git-ignored; values come from Secrets Manager, never from the repo):

   ```toml
   [auth]
   redirect_uri = "https://<your-domain>/oauth2callback"
   cookie_secret = "<long random string>"
   expose_tokens = ["access"]

   [auth.cognito]
   client_id = "<app client id>"
   client_secret = "<app client secret>"
   server_metadata_url = "https://cognito-idp.<region>.amazonaws.com/<user pool id>/.well-known/openid-configuration"
   client_kwargs = { scope = "openid email" }
   ```

3. Create the first admin: invite yourself in the Cognito console, add yourself to the `admin`
   group, then run `uv run python -m app.bootstrap --sub <your Cognito sub>`.
4. Admins manage everyone else through the API: `POST /admin/users` (invite),
   `PUT /admin/users/{sub}/role`, `PUT /admin/users/{sub}/communities` and
   `POST /admin/users/{sub}/disable`. A disabled user is blocked on their next request.

How a request is authorized: the API verifies the Cognito access token, loads the user from
PostgreSQL, and takes the **lower** of the token's group and the stored role. Community
membership always comes from PostgreSQL. An admin has no access to community content just by
being an admin. Nothing in a request body or header can grant a role.

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
