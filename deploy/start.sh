#!/usr/bin/env bash
# Start or update the stack from the release that is already unpacked in /opt/heritagevoice.
# Normally run through `hv-deploy <release-id>`, which fetches the release first. Run as root.
#
# The image is tagged with the release ID, never `latest`. To roll back, deploy an earlier ID.
#
# CI builds the image and uploads it to the releases bucket as releases/<id>.image.tar.gz; this
# script loads it, so nothing is compiled on this machine. A release made before that existed has
# no such file, so it is built here as it always was (which keeps old releases deployable).
set -euo pipefail

cd "$(dirname "$0")/.."
CONFIG_DIR="${HV_CONFIG_DIR:-/etc/heritagevoice}"

ssm_path="$(grep -m1 '^HV_SSM_PATH=' "$CONFIG_DIR/config.env" | cut -d= -f2-)"
./deploy/render-config.sh "$ssm_path" "$CONFIG_DIR/config.env"

# Succeeds when the release's image is on this machine (already, or loaded from the bucket now).
# Fails quietly when CI shipped none; a half-loaded image stops the deploy instead.
have_image() {
  local bucket key="releases/$HV_VERSION.image.tar.gz"
  docker image inspect "heritagevoice:$HV_VERSION" >/dev/null 2>&1 && return 0
  bucket="$(grep -m1 '^HV_RELEASES_BUCKET=' "$CONFIG_DIR/config.env" | cut -d= -f2- || true)"
  [[ -n "$bucket" ]] || return 1
  aws s3api head-object --bucket "$bucket" --key "$key" >/dev/null 2>&1 || return 1
  aws s3 cp --only-show-errors "s3://$bucket/$key" - | docker load >/dev/null || exit 1
}

HV_VERSION="$(cat RELEASE)"
export HV_VERSION
if have_image; then build=(--no-build); else echo "No shipped image; building here"; build=(--build); fi
docker compose --env-file "$CONFIG_DIR/app.env" -f deploy/docker-compose.yml up -d "${build[@]}"
docker compose --env-file "$CONFIG_DIR/app.env" -f deploy/docker-compose.yml ps
echo "Deployed release $HV_VERSION"
