"""Turn candidate IDs from any index into authorized Evidence, loaded from PostgreSQL."""

import hashlib

from sqlalchemy.orm import Session

from app.db.repositories import ChunkRepository, RecordingRepository
from app.models.evidence import Evidence
from app.models.index import ChunkRecord
from app.models.records import REMEDY_NOTICE, HeritageKind, Visibility
from app.retrieval.eligibility import eligible_chunks
from app.security.permissions import Principal, can_read, community_label

PUBLIC_LABEL = "public"


def _labels(chunk: ChunkRecord) -> frozenset[str]:
    """Its community, plus `public` when the chunk is shared with every signed-in user."""
    labels = {community_label(chunk.community_id)}
    if chunk.visibility is Visibility.PUBLIC:
        labels.add(PUBLIC_LABEL)
    return frozenset(labels)


def to_evidence(chunk: ChunkRecord, method: str, notices: tuple[str, ...] = ()) -> Evidence:
    return Evidence(
        evidence_id=chunk.evidence_id,
        document_id=chunk.recording_id,
        document_version=f"v{chunk.version}",
        chunk_id=f"{chunk.kind.value}:{chunk.chunk_index}",
        title=f"Recording {chunk.recording_id[:8]}",
        locator=f"audio:{chunk.recording_id}?t={chunk.start_s}-{chunk.end_s}",
        passage=chunk.text,
        passage_hash=hashlib.sha256(chunk.text.encode()).hexdigest(),
        access_groups=_labels(chunk),
        retrieval_methods=frozenset({method}),
        notices=notices,
    )


def _notices(session: Session, chunks: list[ChunkRecord]) -> dict[str, tuple[str, ...]]:
    """Notices that travel with a passage, read from the recording at the moment of the request."""
    recordings = RecordingRepository(session).get_many([c.recording_id for c in chunks])
    return {
        recording_id: (REMEDY_NOTICE,)
        for recording_id, recording in recordings.items()
        if recording.heritage_kind is HeritageKind.REMEDY
    }


def hydrate(
    session: Session, evidence_ids: list[str], principal: Principal, method: str
) -> list[Evidence]:
    """Evidence for these IDs, in the same order, dropping anything the caller may not see."""
    chunks = ChunkRepository(session).get_many(evidence_ids)
    allowed = eligible_chunks(session, chunks, principal.communities)
    notices = _notices(session, allowed)
    evidence = [to_evidence(c, method, notices.get(c.recording_id, ())) for c in allowed]
    return [item for item in evidence if can_read(principal, item)]
