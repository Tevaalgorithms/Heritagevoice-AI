#!/usr/bin/env bash
# Fetch a release tarball from the private releases bucket and deploy it. Run as root:
#   hv-deploy <release-id>
#
# CI uploads releases/<release-id>.tar.gz and then runs this through Systems Manager, so the
# instance never holds GitHub credentials. Roll back by deploying an earlier release ID.
# Installed to /usr/local/bin/hv-deploy by the instance's first-boot script.
set -euo pipefail

release="${1:-}"
[[ "$release" =~ ^[A-Za-z0-9._-]{1,64}$ ]] || { echo "usage: hv-deploy <release-id>" >&2; exit 1; }

bucket="$(grep -m1 '^HV_RELEASES_BUCKET=' /etc/heritagevoice/config.env | cut -d= -f2-)"
[[ -n "$bucket" ]] || { echo "HV_RELEASES_BUCKET is not set in config.env" >&2; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

aws s3 cp --only-show-errors "s3://$bucket/releases/$release.tar.gz" "$work/release.tar.gz"
mkdir "$work/tree"
tar -xzf "$work/release.tar.gz" --no-same-owner -C "$work/tree"
echo "$release" >"$work/tree/RELEASE"

rm -rf /opt/heritagevoice.previous
if [[ -d /opt/heritagevoice ]]; then mv /opt/heritagevoice /opt/heritagevoice.previous; fi
mv "$work/tree" /opt/heritagevoice
exec /opt/heritagevoice/deploy/start.sh
