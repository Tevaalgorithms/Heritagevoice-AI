"""The API contract is frozen: a schema change fails here until the snapshot is updated on purpose.

Regenerate with:  UPDATE_SNAPSHOTS=1 uv run pytest tests/test_openapi_snapshot.py
Then review the diff of tests/snapshots/openapi.json in the pull request.
"""

import json
import os
from pathlib import Path

from app.api.main import app

SNAPSHOT = Path(__file__).parent / "snapshots" / "openapi.json"


def render() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def test_the_openapi_schema_matches_the_frozen_snapshot():
    if os.environ.get("UPDATE_SNAPSHOTS"):
        SNAPSHOT.write_text(render())
    assert SNAPSHOT.read_text() == render()
