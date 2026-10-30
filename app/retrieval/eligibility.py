"""The single gate every search result passes before it can reach a prompt.

Indexes only narrow candidates. This module re-checks each chunk against PostgreSQL, the source
of truth: the reader belongs to the community, or the chunk is public and its consent still allows
public sharing; the recording is published and not revoked; the consent still permits indexing;
and the chunk is from the version that is currently approved. A stale vector or a leftover row
therefore can never be returned.
"""

from sqlalchemy.orm import Session

from app.db.repositories import ConsentRepository, RecordingRepository, VersionRepository
from app.models.index import ChunkKind, ChunkRecord
from app.models.records import Consent, Recording, RecordingStatus, Right, Subject, Visibility


def _public_ok(recording: Recording, consent: Consent) -> bool:
    """Public reading needs all three: the recording is public, the consent allows public
    sharing, and (checked by the caller) the recording is published and indexable."""
    return recording.visibility is Visibility.PUBLIC and consent.permits(Right.PUBLIC_SHARING)


def _indexable_consent(session: Session, recording: Recording | None) -> Consent | None:
    """The consent of a published recording, if it still permits indexing; otherwise None."""
    if recording is None or recording.status != RecordingStatus.PUBLISHED:
        return None
    consent = ConsentRepository(session).get(recording.consent_id)
    return consent if consent is not None and consent.permits(Right.INDEXING) else None


def _recording_ok(session: Session, recording: Recording | None, public: bool) -> bool:
    """May this recording be read now? `public` is True for a reader outside its community."""
    consent = _indexable_consent(session, recording)
    if consent is None or recording is None:
        return False
    return not public or _public_ok(recording, consent)


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
    session: Session,
    chunk: ChunkRecord,
    communities: frozenset[str],
    verdicts: dict[tuple[str, bool], bool],
) -> bool:
    outsider = chunk.community_id not in communities
    if outsider and chunk.visibility is not Visibility.PUBLIC:
        return False  # an outsider can only ever read public chunks
    key = (chunk.recording_id, outsider)
    if key not in verdicts:
        recording = RecordingRepository(session).get(chunk.recording_id)
        verdicts[key] = _recording_ok(session, recording, outsider)
    return verdicts[key] and _version_current(session, chunk)


def eligible_chunks(
    session: Session, chunks: list[ChunkRecord], communities: frozenset[str]
) -> list[ChunkRecord]:
    """Keep only chunks the caller may see right now, preserving the given order."""
    verdicts: dict[tuple[str, bool], bool] = {}
    return [c for c in chunks if _chunk_ok(session, c, communities, verdicts)]
