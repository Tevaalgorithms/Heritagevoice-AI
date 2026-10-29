#!/usr/bin/env bash
# Deploy or update the stack on the instance. Run as root:  sudo /opt/heritagevoice/deploy/start.sh [ref]
#
# `ref` is a Git branch or tag. Deploy a tag for anything shared, and roll back by running the
# script again with the previous tag. The image is tagged with the Git commit, never `latest`.
set -euo pipefail

REPO=/opt/heritagevoice
CONFIG_DIR=/etc/heritagevoice
cd "$REPO"

if [[ -n "${1:-}" ]]; then
  git fetch --depth 1 origin "$1"
  git checkout -q FETCH_HEAD
fi

ssm_path="$(grep -m1 '^HV_SSM_PATH=' "$CONFIG_DIR/config.env" | cut -d= -f2-)"
./deploy/render-config.sh "$ssm_path" "$CONFIG_DIR/config.env"

HV_VERSION="$(git rev-parse --short HEAD)"
export HV_VERSION
docker compose --env-file "$CONFIG_DIR/app.env" -f deploy/docker-compose.yml up -d --build
docker compose --env-file "$CONFIG_DIR/app.env" -f deploy/docker-compose.yml ps
echo "Deployed commit $HV_VERSION"
