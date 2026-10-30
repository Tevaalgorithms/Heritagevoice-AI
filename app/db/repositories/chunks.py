"""Searchable chunks of approved content, kept in step with what is published."""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.tables import (
    EvidenceChunkRow,
)
from app.models.index import ChunkKind, ChunkRecord


def _to_chunk(row: EvidenceChunkRow) -> ChunkRecord:
    return ChunkRecord(
        evidence_id=row.evidence_id,
        recording_id=row.recording_id,
        community_id=row.community_id,
        kind=ChunkKind(row.kind),
        version=row.version,
        chunk_index=row.chunk_index,
        language=row.language,
        text=row.text,
        passage_hash=row.passage_hash,
        start_s=row.start_s,
        end_s=row.end_s,
        segment_ids=tuple(row.segment_ids),
        speaker=row.speaker,
    )


class ChunkRepository:
    """The searchable copy of approved content. Rows are replaced or deleted as content changes."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def replace_for_recording(self, recording_id: str, chunks: list[ChunkRecord]) -> None:
        self.delete_for_recording(recording_id)
        for chunk in chunks:
            self._session.add(EvidenceChunkRow(**chunk.model_dump(mode="json")))
        self._session.flush()

    def delete_for_recording(self, recording_id: str) -> int:
        result = self._session.execute(
            delete(EvidenceChunkRow).where(EvidenceChunkRow.recording_id == recording_id)
        )
        self._session.flush()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    def get_many(self, evidence_ids: list[str]) -> list[ChunkRecord]:
        """Chunks for these IDs, in the order given; unknown IDs are skipped."""
        if not evidence_ids:
            return []
        query = select(EvidenceChunkRow).where(EvidenceChunkRow.evidence_id.in_(evidence_ids))
        found = {r.evidence_id: _to_chunk(r) for r in self._session.scalars(query)}
        return [found[i] for i in evidence_ids if i in found]

    def for_communities(self, communities: frozenset[str], limit: int = 5000) -> list[ChunkRecord]:
        query = (
            select(EvidenceChunkRow)
            .where(EvidenceChunkRow.community_id.in_(communities))
            .order_by(EvidenceChunkRow.evidence_id)
            .limit(limit)
        )
        return [_to_chunk(r) for r in self._session.scalars(query)]

    def recording_ids(self) -> list[str]:
        """Recordings that currently have indexed chunks."""
        return sorted(set(self._session.scalars(select(EvidenceChunkRow.recording_id))))

    def ids_for_recording(self, recording_id: str) -> list[str]:
        query = select(EvidenceChunkRow.evidence_id).where(
            EvidenceChunkRow.recording_id == recording_id
        )
        return sorted(self._session.scalars(query))
