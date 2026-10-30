#!/usr/bin/env bash
# Build the app's runtime config on the instance. Run as root.
#
#   render-config.sh /heritagevoice/<env> /path/to/config.env
#
# config.env holds the non-secret settings (written by cloud-init from Terraform values).
# Secrets are read from AWS SSM Parameter Store (SecureString) under the given path, using the
# instance's IAM role; nothing secret is stored in the repository, the image or Terraform state.
# Output (mode 0600): /etc/heritagevoice/app.env (root only) and /etc/heritagevoice/secrets.toml,
# which is owned by the UI container's user (uid 10001, set in the Dockerfile) so Streamlit can read it.
set -euo pipefail
umask 077

PARAM_PATH="${1:?usage: render-config.sh /heritagevoice/<env> <config.env>}"
CONFIG_ENV="${2:?usage: render-config.sh /heritagevoice/<env> <config.env>}"
OUT_DIR="${HV_CONFIG_DIR:-/etc/heritagevoice}"
SAFE_VALUE='^[A-Za-z0-9._~+/=:@,-]*$'

install -d -m 0750 "$OUT_DIR"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

cat "$CONFIG_ENV" >"$tmp"
aws ssm get-parameters-by-path --path "$PARAM_PATH" --with-decryption \
  --query 'Parameters[].[Name,Value]' --output text |
  while IFS=$'\t' read -r name value; do
    [[ "$value" =~ $SAFE_VALUE ]] || { echo "Parameter ${name##*/} has unsupported characters" >&2; exit 1; }
    echo "${name##*/}=$value"
  done >>"$tmp"

get() { grep -m1 "^$1=" "$tmp" | cut -d= -f2- || true; }
require() { [[ -n "$(get "$1")" ]] || { echo "Missing setting: $1" >&2; exit 1; }; }

for key in HV_DOMAIN POSTGRES_PASSWORD HV_COOKIE_SECRET HV_COGNITO_CLIENT_SECRET \
  HERITAGEVOICE_COGNITO_REGION HERITAGEVOICE_COGNITO_USER_POOL_ID HERITAGEVOICE_COGNITO_APP_CLIENT_ID; do
  require "$key"
done

install -m 0600 "$tmp" "$OUT_DIR/app.env"

region="$(get HERITAGEVOICE_COGNITO_REGION)"
pool="$(get HERITAGEVOICE_COGNITO_USER_POOL_ID)"
cat >"$OUT_DIR/secrets.toml" <<TOML
[auth]
redirect_uri = "https://$(get HV_DOMAIN)/oauth2callback"
cookie_secret = "$(get HV_COOKIE_SECRET)"
expose_tokens = ["access"]

[auth.cognito]
client_id = "$(get HERITAGEVOICE_COGNITO_APP_CLIENT_ID)"
client_secret = "$(get HV_COGNITO_CLIENT_SECRET)"
server_metadata_url = "https://cognito-idp.${region}.amazonaws.com/${pool}/.well-known/openid-configuration"
client_kwargs = { scope = "openid email" }
TOML
chmod 0600 "$OUT_DIR/secrets.toml"
chown "${HV_UI_OWNER:-10001:10001}" "$OUT_DIR/secrets.toml"
echo "Wrote $OUT_DIR/app.env and $OUT_DIR/secrets.toml"
