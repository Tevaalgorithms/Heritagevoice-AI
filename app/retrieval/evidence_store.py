"""Turn candidate IDs from any index into authorized Evidence, loaded from PostgreSQL."""

import hashlib

from sqlalchemy.orm import Session

from app.db.repositories import ChunkRepository
from app.models.evidence import Evidence
from app.models.index import ChunkRecord
from app.retrieval.eligibility import eligible_chunks
from app.security.permissions import Principal, can_read, community_label


def to_evidence(chunk: ChunkRecord, method: str) -> Evidence:
    return Evidence(
        evidence_id=chunk.evidence_id,
        document_id=chunk.recording_id,
        document_version=f"v{chunk.version}",
        chunk_id=f"{chunk.kind.value}:{chunk.chunk_index}",
        title=f"Recording {chunk.recording_id[:8]}",
        locator=f"audio:{chunk.recording_id}?t={chunk.start_s}-{chunk.end_s}",
        passage=chunk.text,
        passage_hash=hashlib.sha256(chunk.text.encode()).hexdigest(),
        access_groups=frozenset({community_label(chunk.community_id)}),
        retrieval_methods=frozenset({method}),
    )


def hydrate(
    session: Session, evidence_ids: list[str], principal: Principal, method: str
) -> list[Evidence]:
    """Evidence for these IDs, in the same order, dropping anything the caller may not see."""
    chunks = ChunkRepository(session).get_many(evidence_ids)
    allowed = eligible_chunks(session, chunks, principal.communities)
    evidence = [to_evidence(chunk, method) for chunk in allowed]
    return [item for item in evidence if can_read(principal, item)]
