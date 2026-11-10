"""Throw away a recording that nobody has approved yet, for example one recorded by mistake.

Unlike withdrawing (which hides a shared recording and keeps the record), this erases the audio,
the transcript and the translation, and everything written about them. It is allowed only for the
person who made the recording (or an admin), and only while the recording was never approved and
nothing is still processing it. Anything that has been shared goes through withdrawing instead,
because search, answers and the graph may already have used it.
"""

from sqlalchemy.orm import Session

from app.db.repositories import (
    JobRepository,
    RecordingRepository,
    ReviewDecisionRepository,
)
from app.models.records import Recording, RecordingStatus
from app.ports import AudioStore
from app.security.permissions import Principal
from app.security.roles import Role

DISCARDABLE = (RecordingStatus.DRAFT, RecordingStatus.REVIEW)


class DiscardRefusedError(Exception):
    """The recording cannot be thrown away. `code` is safe to show; `status` is the HTTP status."""

    def __init__(self, code: str, status: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def _was_approved(session: Session, recording_id: str) -> bool:
    decisions = ReviewDecisionRepository(session).for_recording(recording_id)
    return any(decision.approved for decision in decisions)


def _is_yours(principal: Principal, recording: Recording) -> bool:
    return recording.uploader_id == principal.user_id or principal.role is Role.ADMIN


def _shared_already(session: Session, recording: Recording) -> bool:
    return recording.status not in DISCARDABLE or _was_approved(session, recording.id)


def _check(session: Session, principal: Principal, recording: Recording) -> None:
    if not _is_yours(principal, recording):
        raise DiscardRefusedError("not_found", 404)
    if _shared_already(session, recording):
        raise DiscardRefusedError("already_shared")
    if JobRepository(session).any_open(recording.id):
        raise DiscardRefusedError("still_processing")


def discard_recording(
    session: Session, store: AudioStore, principal: Principal, recording_id: str
) -> None:
    """Erase the recording, its audio and its transcript and translation. The audio is deleted
    before the database changes are saved, so if storage fails nothing is half-erased."""
    recordings = RecordingRepository(session)
    recording = recordings.get(recording_id)
    if recording is None:
        raise DiscardRefusedError("not_found", 404)
    _check(session, principal, recording)
    recordings.erase(recording_id)
    if recording.audio_key:
        store.delete(recording.audio_key)
