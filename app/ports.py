"""Interfaces the agents depend on. Vendors (Pinecone, Neo4j, ASR, LLM) live in adapters.

Every method that returns evidence takes the trusted `Principal`; adapters must filter by
it inside the query, not after results are returned.
"""

from typing import Protocol, runtime_checkable

from app.models.evidence import Evidence
from app.models.transcript import Segment
from app.security.permissions import Principal
from app.security.roles import Role


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
    def transcribe(self, audio_key: str, language: str) -> list[Segment]:
        """Transcribe the stored audio object. Segments must be ordered and inside the audio."""
        ...


@runtime_checkable
class Translator(Protocol):
    def translate(self, segments: list[Segment], target_language: str) -> list[Segment]: ...


@runtime_checkable
class IdentityProvider(Protocol):
    """Account administration in the identity service (Amazon Cognito in production)."""

    def invite_user(self, email: str, role: Role) -> str:
        """Create the account, put it in the role's group, return the stable subject ID."""
        ...

    def set_role(self, sub: str, role: Role) -> None: ...

    def disable_user(self, sub: str) -> None:
        """Disable the account and sign it out everywhere."""
        ...


@runtime_checkable
class AudioStore(Protocol):
    """Private audio storage. Keys never contain file names or other personal data."""

    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...
