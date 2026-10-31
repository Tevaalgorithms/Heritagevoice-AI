#!/usr/bin/env bash
# Creates the Pinecone index HeritageVoice searches (plain vectors, 1024 dimensions, cosine).
# Asks for the API key with hidden input; the key is never printed or saved.
set -euo pipefail
cd "$(dirname "$0")/.."
read -r -s -p "Pinecone API key (hidden), then Enter: " PINECONE_API_KEY
echo
export PINECONE_API_KEY
uv run python - <<'PY'
import os

from pinecone import Pinecone, ServerlessSpec

pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
pc.create_index(
    name="heritagevoice-prod",
    dimension=1024,
    metric="cosine",
    spec=ServerlessSpec(cloud="aws", region="us-east-1"),
)
print("created heritagevoice-prod")
PY
