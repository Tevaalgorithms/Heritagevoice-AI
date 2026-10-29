"""Withdraw access: mark records revoked and stop work that is queued or running.

Revocation is immediate and idempotent. Search indexes and the graph are rebuilt from approved,
non-revoked records, and playback is denied from the stored status, so nothing stale is served.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.repositories import ConsentRepository, JobRepository, RecordingRepository
from app.index_sync import drop_index
from app.indexing import UNINDEX_KIND
from app.models.records import RecordingStatus

CONSENT_CODE = "consent"
CLEANUP = (UNINDEX_KIND,)  # never cancel the jobs that remove content from the indexes


@dataclass(frozen=True)
class Revocation:
    recordings: int
    jobs_stopped: int


def revoke_consent(session: Session, consent_id: str) -> Revocation | None:
    """Revoke a consent and every recording that relies on it. None if the consent is unknown."""
    if not ConsentRepository(session).revoke(consent_id):
        return None
    recordings = RecordingRepository(session)
    ids = recordings.ids_by_consent(consent_id)
    for recording_id in ids:
        recordings.set_status(recording_id, RecordingStatus.REVOKED)
    stopped = JobRepository(session).fail_open_jobs(ids, CONSENT_CODE, CLEANUP)
    for recording_id in ids:
        drop_index(session, recording_id)
    return Revocation(len(ids), stopped)


def revoke_recording(session: Session, recording_id: str) -> Revocation | None:
    """Revoke one recording (not its consent). None if the recording is unknown."""
    recordings = RecordingRepository(session)
    if recordings.get(recording_id) is None:
        return None
    recordings.set_status(recording_id, RecordingStatus.REVOKED)
    stopped = JobRepository(session).fail_open_jobs([recording_id], CONSENT_CODE, CLEANUP)
    drop_index(session, recording_id)
    return Revocation(1, stopped)
