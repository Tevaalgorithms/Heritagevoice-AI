#!/usr/bin/env bash
# Start or update the stack from the release that is already unpacked in /opt/heritagevoice.
# Normally run through `hv-deploy <release-id>`, which fetches the release first. Run as root.
#
# The image is tagged with the release ID, never `latest`. To roll back, deploy an earlier ID.
set -euo pipefail

cd "$(dirname "$0")/.."
CONFIG_DIR=/etc/heritagevoice

ssm_path="$(grep -m1 '^HV_SSM_PATH=' "$CONFIG_DIR/config.env" | cut -d= -f2-)"
./deploy/render-config.sh "$ssm_path" "$CONFIG_DIR/config.env"

HV_VERSION="$(cat RELEASE)"
export HV_VERSION
docker compose --env-file "$CONFIG_DIR/app.env" -f deploy/docker-compose.yml up -d --build
docker compose --env-file "$CONFIG_DIR/app.env" -f deploy/docker-compose.yml ps
echo "Deployed release $HV_VERSION"
