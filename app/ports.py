"""Interfaces the agents depend on. Vendors (Pinecone, Neo4j, ASR, LLM) live in adapters.

Every method that returns evidence takes the trusted `Principal`; adapters must filter by
it inside the query, not after results are returned.
"""

from typing import Any, Protocol, runtime_checkable

from pydantic import SecretStr

from app.models.evidence import Evidence
from app.models.graph_path import GraphPath
from app.models.llm import ModelParams, ProbeResult
from app.models.records import GraphAssertion, Visibility
from app.models.transcript import Segment
from app.models.users import Signup
from app.security.permissions import Principal
from app.security.roles import Role


@runtime_checkable
class VectorStore(Protocol):
    """Meaning-based search over approved content."""

    def upsert(self, items: list[Evidence]) -> None: ...

    def delete_recording(self, recording_id: str, community_id: str) -> None:
        """Remove every vector of one recording (they all share its ID as a prefix)."""
        ...

    def search(self, query: str, principal: Principal, limit: int = 20) -> list[Evidence]: ...


@runtime_checkable
class GraphStore(Protocol):
    """Relationship search over the reviewed knowledge graph."""

    def traverse(self, query: str, principal: Principal, max_hops: int = 2) -> list[Evidence]: ...


@runtime_checkable
class GraphReader(Protocol):
    """Finds candidate paths in the knowledge graph. A path is a lead, never evidence by itself."""

    def paths(self, question: str, communities: frozenset[str], limit: int) -> list[GraphPath]: ...


@runtime_checkable
class GraphProjection(Protocol):
    """The writable side of the knowledge graph: a rebuildable copy of approved assertions."""

    def replace_recording(
        self,
        recording_id: str,
        community_id: str,
        visibility: Visibility,
        assertions: list[GraphAssertion],
    ) -> None: ...

    def delete_recording(self, recording_id: str) -> None: ...

    def recording_ids(self) -> list[str]: ...


@runtime_checkable
class Transcriber(Protocol):
    """Turns audio into timed text."""

    def transcribe(self, audio_key: str, language: str) -> list[Segment]:
        """Transcribe the stored audio object. Segments must be ordered and inside the audio."""
        ...


@runtime_checkable
class Translator(Protocol):
    """Turns segments into another language, keeping their IDs."""

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

    def list_signups(self) -> list[Signup]:
        """Self-created, email-confirmed, enabled accounts (the caller removes approved ones)."""
        ...

    def find_sub(self, email: str) -> str | None:
        """The account with this email address, if there is one."""
        ...

    def email_of(self, sub: str) -> str | None:
        """The email address of an account, if it still exists."""
        ...

    def emails_for(self, subs: list[str]) -> dict[str, str]:
        """The email address of each of these accounts that still exists, in one pass."""
        ...


@runtime_checkable
class AudioStore(Protocol):
    """Private audio storage. Keys never contain file names or other personal data."""

    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...


@runtime_checkable
class ModelTester(Protocol):
    """Checks that a model setting works with the configured key. Never returns the key."""

    def check(self, params: ModelParams, api_key: SecretStr | None) -> ProbeResult: ...


@runtime_checkable
class Embedder(Protocol):
    """Turns text into vectors. Documents and queries are embedded differently by some models."""

    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class Invoker(Protocol):
    """One structured model call for an agent. The real one tries models and fall-backs in order."""

    def invoke(self, inputs: dict[str, Any]) -> Any: ...
