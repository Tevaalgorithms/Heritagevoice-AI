"""Shared source and output contracts. Stable IDs originate in ingestion."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


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


class QueryResponse(BaseModel):
    """The answer to a question, with its citations and outcome."""

    status: str
    answer: str = ""
    citations: list[Evidence] = Field(default_factory=list)
    request_id: str
    conversation_id: str | None = None
