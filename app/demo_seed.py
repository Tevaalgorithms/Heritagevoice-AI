"""Put a small multilingual demo library into the system, or take it out again.

    python -m app.demo_seed seed      # add the demo recordings and index them for search
    python -m app.demo_seed remove    # withdraw them (they leave search, answers and the Library)

The recordings are synthetic (`demo_recordings.json`): invented text in nine languages with English
translations, shared openly, each with a computer-made voice (`demo_audio/`) where one exists. They
go through the same tables and the same indexing as real recordings, so search, the Library and
answers behave as they will for real material.
Every id starts with `demo-`, so only demo material is ever touched. Safe to repeat.
"""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.adapters.audio_store import S3AudioStore
from app.audio import sniff_type
from app.config import Settings
from app.db.engine import engine_from_settings
from app.db.repositories import Media, RecordingRepository
from app.indexing import IndexDeps, index_one, remove_recording
from app.models.credit import SYNTHETIC_NOTE
from app.models.groups import OPEN_COMMUNITY
from app.models.records import RecordingStatus, Right
from app.ports import AudioStore
from app.retrieval_evaluation import publish_fixture
from app.revocation import revoke_consent

CORPUS = Path(__file__).with_name("demo_recordings.json")
AUDIO = Path(__file__).with_name("demo_audio")  # one synthetic-voice clip per recording, if any
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
        "note": SYNTHETIC_NOTE,
        "consent": {"rights": OPEN_RIGHTS, "policy_version": "v1"},
    }


def _clip(recording_id: str) -> bytes | None:
    path = AUDIO / f"{recording_id}.m4a"
    return path.read_bytes() if path.exists() else None


def _attach_audio(deps: IndexDeps, store: AudioStore, recording: dict[str, Any]) -> bool:
    """Store the recording's synthetic-voice clip and link it, if there is one. True if linked.
    The clip is a fixed length (every segment fills its slot), so the segment times still match."""
    data = _clip(recording["id"])
    if data is None or sniff_type(data[:16]) is None:
        return False
    key = f"recordings/{OPEN_COMMUNITY}/{recording['id']}/original"
    store.put(key, data, "audio/mp4")
    length = recording["segments"][-1]["end_s"]
    media = Media(key, "audio/mp4", len(data), length, SYNTHETIC_NOTE)
    with deps.sessions() as session:
        RecordingRepository(session).set_media(recording["id"], media)
    return True


def seed(deps: IndexDeps, store: AudioStore | None = None) -> tuple[list[str], list[str]]:
    """Add and index what is missing, and give each recording its synthetic voice when there is a
    store to put it in (also for recordings added earlier). Returns (added ids, ids already
    there)."""
    added: list[str] = []
    present: list[str] = []
    for recording in load_corpus()["recordings"]:
        with deps.sessions() as session:
            exists = RecordingRepository(session).get(recording["id"]) is not None
            if not exists:
                publish_fixture(session, as_fixture(recording))
        if exists:
            present.append(recording["id"])
        else:
            index_one(deps, recording["id"])
            added.append(recording["id"])
        if store is not None:
            _attach_audio(deps, store, recording)
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
        bucket = settings.audio_bucket
        store = S3AudioStore(bucket, settings.audio_kms_key_id) if bucket else None
        added, present = seed(deps, store)
        print(f"added {len(added)} demo recordings; {len(present)} were already there")
    else:
        print(f"withdrew {len(remove(deps))} demo recordings")


if __name__ == "__main__":
    main()
