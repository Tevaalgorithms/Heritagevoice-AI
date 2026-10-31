"""Shared source and output contracts. Stable IDs originate in ingestion."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.languages import BY_CODE


class Route(StrEnum):
    """How a question will be answered: from text, from the graph, both, or not at all."""

    HYBRID = "hybrid"
    GRAPH = "graph"
    BOTH = "both"
    CLARIFY = "clarify"
    REFUSE = "refuse"


class Evidence(BaseModel):
    """One cited passage with its source, version, timing and access labels."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_version: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    title: str
    locator: str = Field(min_length=1)
    passage: str = Field(min_length=1)
    passage_hash: str = Field(min_length=1)
    access_groups: frozenset[str] = Field(min_length=1)
    retrieval_methods: frozenset[str] = Field(min_length=1)
    graph_paths: tuple[tuple[str, ...], ...] = ()
    notices: tuple[str, ...] = ()  # must be shown with the passage (for example, for remedies)


class Claim(BaseModel):
    """One statement in an answer and the evidence that supports it."""

    text: str
    evidence_ids: list[str] = Field(min_length=1)
    verdict: str = "unverified"


class QueryRequest(BaseModel):
    """A user's question."""

    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None
    response_language: str | None = None  # a supported language code; None = the question's own

    @field_validator("response_language")
    @classmethod
    def _supported(cls, value: str | None) -> str | None:
        if value is not None and value not in BY_CODE:
            raise ValueError("unsupported language")
        return value


class Citation(BaseModel):
    """A source as shown to the reader: the passage and where it is in the recording. It carries
    no access labels, community, uploader or storage location."""

    evidence_id: str
    recording_id: str
    title: str
    passage: str
    start_s: float
    end_s: float
    notices: list[str] = Field(default_factory=list)


class QueryResponse(BaseModel):
    """The answer to a question, with its citations and outcome.

    `status` is one of answered, partial, insufficient_evidence, clarify or refused."""

    status: str
    answer: str = ""
    citations: list[Citation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    request_id: str
    conversation_id: str | None = None
