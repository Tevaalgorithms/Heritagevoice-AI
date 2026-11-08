"""Put a small multilingual demo library into the system, or take it out again.

    python -m app.demo_seed seed      # add the demo recordings and index them for search
    python -m app.demo_seed remove    # withdraw them (they leave search, answers and the Library)

The recordings are synthetic (`demo_recordings.json`): invented text in nine languages with English
translations, shared openly, with no audio. They go through the same tables and the same indexing
as real recordings, so search, the Library and answers behave as they will for real material.
Every id starts with `demo-`, so only demo material is ever touched. Safe to repeat.
"""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.config import Settings
from app.db.engine import engine_from_settings
from app.db.repositories import RecordingRepository
from app.indexing import IndexDeps, index_one, remove_recording
from app.models.groups import OPEN_COMMUNITY
from app.models.records import RecordingStatus, Right
from app.retrieval_evaluation import publish_fixture
from app.revocation import revoke_consent

CORPUS = Path(__file__).with_name("demo_recordings.json")
PREFIX = "demo-"
UPLOADER = "demo-seed"
OPEN_RIGHTS = [right.value for right in Right]  # the speakers agreed to everything, openly


def load_corpus() -> dict[str, Any]:
    """The demo recordings and the questions the evaluation asks about them."""
    corpus: dict[str, Any] = json.loads(CORPUS.read_text(encoding="utf-8"))
    return corpus


def as_fixture(recording: dict[str, Any]) -> dict[str, Any]:
    """A corpus entry in the shape `publish_fixture` takes: open to everyone, all rights granted."""
    return {
        **recording,
        "community_id": OPEN_COMMUNITY,
        "visibility": "public",
        "uploader": UPLOADER,
        "consent": {"rights": OPEN_RIGHTS, "policy_version": "v1"},
    }


def seed(deps: IndexDeps) -> tuple[list[str], list[str]]:
    """Add and index what is missing. Returns (added ids, ids that were already there)."""
    added: list[str] = []
    present: list[str] = []
    for recording in load_corpus()["recordings"]:
        with deps.sessions() as session:
            if RecordingRepository(session).get(recording["id"]) is not None:
                present.append(recording["id"])
                continue
            publish_fixture(session, as_fixture(recording))
        index_one(deps, recording["id"])
        added.append(recording["id"])
    return added, present


def remove(deps: IndexDeps) -> list[str]:
    """Withdraw every demo recording that is still shown. The rows stay, hidden, as for any
    withdrawn recording; the search entries and vectors are removed."""
    withdrawn: list[str] = []
    for recording in load_corpus()["recordings"]:
        with deps.sessions() as session:
            found = RecordingRepository(session).get(recording["id"])
            if found is None or found.status is RecordingStatus.REVOKED:
                continue
            revoke_consent(session, found.consent_id)
        remove_recording(deps, recording["id"])
        withdrawn.append(recording["id"])
    return withdrawn


def main(argv: Sequence[str] | None = None) -> None:
    from app.worker_setup import index_deps  # noqa: PLC0415  (loads the model and graph clients)

    parser = argparse.ArgumentParser(description="Add or remove the synthetic demo library")
    parser.add_argument("action", choices=("seed", "remove"))
    action = parser.parse_args(argv).action
    settings = Settings()
    deps = index_deps(settings, engine_from_settings(settings))
    if action == "seed":
        added, present = seed(deps)
        print(f"added {len(added)} demo recordings; {len(present)} were already there")
    else:
        print(f"withdrew {len(remove(deps))} demo recordings")


if __name__ == "__main__":
    main()
