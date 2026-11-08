#!/usr/bin/env bash
# Start the real stack on a throwaway database and check that it comes up, before anything is
# deployed. It uses the real compose file, the real render-config.sh and the image you built, so a
# change that builds but cannot start (a broken migration, a missing setting, a failing import)
# fails here instead of in production. Only the cloud parts are left out: Parameter Store is a
# stub, and Caddy (which needs a real domain for its certificate) is not started.
#
#   scripts/rehearse.sh [base-ref]
#
# With a base ref (the commit production is on), the database is first migrated with that
# commit's migrations, then the new ones run on top: the same path a real deploy takes.
# Set REHEARSAL_SKIP_BUILD=1 to reuse an existing heritagevoice:rehearsal image.
set -euo pipefail

cd "$(dirname "$0")/.."
base_ref="${1:-}"
work="$(mktemp -d)"
project=hvrehearsal
failed=0

export HV_VERSION=rehearsal
export HV_CONFIG_DIR="$work/config"
export HV_DATA_DIR="$work/data"
export HV_UI_OWNER="$(id -u):$(id -g)"
mkdir -p "$HV_CONFIG_DIR" "$HV_DATA_DIR" "$work/bin"

compose() { docker compose -p "$project" --env-file "$HV_CONFIG_DIR/app.env" -f deploy/docker-compose.yml "$@"; }

cleanup() {
  compose down -v --remove-orphans >/dev/null 2>&1 || true
  # The database files belong to another user, so remove them from inside a container.
  docker run --rm -u 0 -v "$work":/w --entrypoint rm heritagevoice:rehearsal -rf /w/data >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

# The same settings first boot writes (infra/single-instance/user_data.sh.tftpl), with fake values.
cat >"$work/config.env" <<CONFIG
HV_DOMAIN=localhost
POSTGRES_PASSWORD=rehearsal-only
HV_COOKIE_SECRET=rehearsal-only-cookie-secret
HV_COGNITO_CLIENT_SECRET=rehearsal-only
HERITAGEVOICE_ENVIRONMENT=production
HERITAGEVOICE_API_URL=http://api:8000
HERITAGEVOICE_ASR_PROVIDER=fake
HERITAGEVOICE_COGNITO_REGION=us-west-2
HERITAGEVOICE_COGNITO_USER_POOL_ID=us-west-2_REHEARSAL
HERITAGEVOICE_COGNITO_APP_CLIENT_ID=rehearsal
CONFIG
# A stand-in for the AWS CLI: Parameter Store returns nothing, so config.env is the only source.
printf '#!/usr/bin/env bash\nexit 0\n' >"$work/bin/aws"
chmod +x "$work/bin/aws"
PATH="$work/bin:$PATH" ./deploy/render-config.sh /heritagevoice/rehearsal "$work/config.env"
chmod 0644 "$HV_CONFIG_DIR/secrets.toml"

wait_for() {
  local what="$1"
  shift
  for _ in $(seq 1 60); do
    if "$@" >/dev/null 2>&1; then echo "ok      $what"; return 0; fi
    sleep 2
  done
  echo "FAILED  $what" >&2
  failed=1
}

api_get() {
  compose exec -T api python -c "import sys, urllib.request as u; sys.stdout.write(u.urlopen('http://127.0.0.1:8000$1', timeout=5).read().decode())"
}
ui_healthy() {
  compose exec -T ui python -c "import urllib.request as u; assert u.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=5).read() == b'ok'"
}
migrated_cleanly() { [[ "$(docker inspect -f '{{.State.ExitCode}}' "$(compose ps -aq migrate)")" == 0 ]]; }
at_head() { compose exec -T api alembic current | grep -q '(head)'; }
worker_running() { [[ "$(docker inspect -f '{{.State.Running}}' "$(compose ps -q worker)")" == true ]]; }
ready() { api_get /ready | grep -q '"ready":true'; }
public_search() { api_get /v1/public/library | grep -q '"items"'; }

if [[ "${REHEARSAL_SKIP_BUILD:-}" != 1 ]]; then docker build -q -t heritagevoice:rehearsal .; fi

compose up -d --wait postgres

if [[ -n "$base_ref" ]] && git rev-parse --verify -q "$base_ref^{commit}" >/dev/null; then
  echo "Migrating with $base_ref first, as production is on it"
  mkdir -p "$work/base"
  git archive "$base_ref" migrations | tar -x -C "$work/base"
  compose run --rm --no-deps -T -v "$work/base/migrations:/app/migrations:ro" migrate
else
  echo "No base commit given or found: migrating a fresh database only"
fi

# A migration that fails stops `up` itself, so say so and show why before anything else.
if ! compose up -d --no-build api ui worker; then
  echo "FAILED  the stack did not start (see the logs below)" >&2
  compose logs --no-color --tail 40 migrate >&2 || true
  exit 1
fi

wait_for "the new migrations ran cleanly" migrated_cleanly
wait_for "the database is at the latest revision" at_head
wait_for "the API reports ready" ready
wait_for "a visitor's search answers" public_search
wait_for "the interface is serving" ui_healthy
wait_for "the worker is running" worker_running

if [[ "$failed" != 0 ]]; then
  compose ps -a >&2 || true
  compose logs --no-color --tail 40 migrate api ui worker >&2 || true
  exit 1
fi
echo "Rehearsal passed"
