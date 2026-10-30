"""What the search indexes hold: one row per chunk of an approved transcript or translation."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ChunkKind(StrEnum):
    """Whether a searchable chunk comes from a transcript or a translation."""

    TRANSCRIPT = "transcript"
    TRANSLATION = "translation"


class ChunkRecord(BaseModel):
    """A searchable passage. Postgres is the source of truth; Pinecone holds only vectors."""

    model_config = ConfigDict(frozen=True)
    evidence_id: str = Field(min_length=1)
    recording_id: str
    community_id: str
    kind: ChunkKind
    version: int = Field(ge=1)
    chunk_index: int = Field(ge=0)
    language: str
    text: str = Field(min_length=1)
    passage_hash: str
    start_s: float
    end_s: float
    segment_ids: tuple[str, ...]
    speaker: str | None = None
