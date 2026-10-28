#!/usr/bin/env bash
# One-time, per clone: turn on the secret-scanning commit hook.
set -euo pipefail
cd "$(dirname "$0")/.."
git config core.hooksPath .githooks
chmod +x .githooks/pre-commit
echo "Secret scanning enabled for commits in this clone."
