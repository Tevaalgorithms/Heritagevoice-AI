"""The single gate every search result passes before it can reach a prompt.

Indexes only narrow candidates. This module re-checks each chunk against PostgreSQL, the source
of truth: the caller belongs to the community, the recording is published and not revoked, the
consent still permits indexing, and the chunk is from the version that is currently approved.
A stale vector or a leftover row therefore can never be returned.
"""

from sqlalchemy.orm import Session

from app.db.repositories import ConsentRepository, RecordingRepository, VersionRepository
from app.models.index import ChunkKind, ChunkRecord
from app.models.records import Recording, RecordingStatus, Right, Subject


def _recording_ok(session: Session, recording: Recording | None) -> bool:
    if recording is None or recording.status != RecordingStatus.PUBLISHED:
        return False
    consent = ConsentRepository(session).get(recording.consent_id)
    return consent is not None and consent.permits(Right.INDEXING)


def _version_current(session: Session, chunk: ChunkRecord) -> bool:
    versions = VersionRepository(session)
    transcript = versions.approved(chunk.recording_id, Subject.TRANSCRIPT)
    if transcript is None:
        return False
    if chunk.kind is ChunkKind.TRANSCRIPT:
        return chunk.version == transcript.version
    translation = versions.approved(chunk.recording_id, Subject.TRANSLATION)
    return (
        translation is not None
        and chunk.version == translation.version
        and translation.transcript_version == transcript.version
    )


def _chunk_ok(
    session: Session, chunk: ChunkRecord, communities: frozenset[str], verdicts: dict[str, bool]
) -> bool:
    if chunk.community_id not in communities:
        return False
    if chunk.recording_id not in verdicts:
        recording = RecordingRepository(session).get(chunk.recording_id)
        verdicts[chunk.recording_id] = _recording_ok(session, recording)
    return verdicts[chunk.recording_id] and _version_current(session, chunk)


def eligible_chunks(
    session: Session, chunks: list[ChunkRecord], communities: frozenset[str]
) -> list[ChunkRecord]:
    """Keep only chunks the caller may see right now, preserving the given order."""
    verdicts: dict[str, bool] = {}
    return [c for c in chunks if _chunk_ok(session, c, communities, verdicts)]
