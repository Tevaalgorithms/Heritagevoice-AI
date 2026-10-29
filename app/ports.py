"""Interfaces the agents depend on. Vendors (Pinecone, Neo4j, ASR, LLM) live in adapters.

Every method that returns evidence takes the trusted `Principal`; adapters must filter by
it inside the query, not after results are returned.
"""

from typing import Protocol, runtime_checkable

from app.models.evidence import Evidence
from app.models.transcript import Segment
from app.security.permissions import Principal


@runtime_checkable
class VectorStore(Protocol):
    def upsert(self, items: list[Evidence]) -> None: ...

    def delete(self, evidence_ids: list[str]) -> None: ...

    def search(self, query: str, principal: Principal, limit: int = 20) -> list[Evidence]: ...


@runtime_checkable
class GraphStore(Protocol):
    def traverse(self, query: str, principal: Principal, max_hops: int = 2) -> list[Evidence]: ...


@runtime_checkable
class Transcriber(Protocol):
    def transcribe(self, audio: bytes, language: str) -> list[Segment]: ...


@runtime_checkable
class Translator(Protocol):
    def translate(self, segments: list[Segment], target_language: str) -> list[Segment]: ...
