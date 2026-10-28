"""Shared source and output contracts. Stable IDs originate in ingestion."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Route(StrEnum):
    HYBRID = "hybrid"
    GRAPH = "graph"
    BOTH = "both"
    CLARIFY = "clarify"
    REFUSE = "refuse"


class Evidence(BaseModel):
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
    text: str
    evidence_ids: list[str] = Field(min_length=1)
    verdict: str = "unverified"


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None


class QueryResponse(BaseModel):
    status: str
    answer: str = ""
    citations: list[Evidence] = Field(default_factory=list)
    request_id: str
    conversation_id: str | None = None
