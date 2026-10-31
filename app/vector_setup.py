"""The vector store, following the Pinecone settings saved in the admin portal.

`RuntimeVectorStore` looks at the saved key, index, embedding model and dimension each time it is
used (the reader keeps them in memory for a few minutes). It builds the real Pinecone store the
first time they are all present, and builds a new one if any of them changes. Until Pinecone is
configured it does nothing: searches find nothing and indexing skips vectors, so keyword search
keeps working. Saving a key in the portal therefore needs no redeploy.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from pinecone import Pinecone
from sqlalchemy.engine import Engine

from app.adapters.pinecone_store import PineconeEmbedder, PineconeVectorStore
from app.config import Settings
from app.db.session import session_scope
from app.models.evidence import Evidence
from app.ports import VectorStore
from app.retrieval.evidence_store import hydrate
from app.runtime_store import RuntimeStore
from app.secrets import SecretReader, secret_text, secrets_for
from app.security.permissions import Principal


@dataclass(frozen=True)
class PineconeConfig:
    """Everything needed to talk to Pinecone. The key never shows in a repr or a log line."""

    api_key: str = field(repr=False)
    index: str
    model: str
    dimension: int


Builder = Callable[[PineconeConfig], VectorStore]


def _dimension(reader: SecretReader, default: int) -> int:
    raw = secret_text(reader, "EMBEDDING_DIMENSION")
    return int(raw) if raw and raw.isdigit() else default


def current_config(reader: SecretReader, defaults: Settings) -> PineconeConfig | None:
    """The saved settings, with the environment as defaults. None until key and index exist."""
    key, index = secret_text(reader, "PINECONE_API_KEY"), secret_text(reader, "PINECONE_INDEX")
    if not key or not index:
        return None
    model = secret_text(reader, "EMBEDDING_MODEL") or defaults.embedding_model
    return PineconeConfig(key, index, model, _dimension(reader, defaults.embedding_dimension))


class RuntimeVectorStore:
    """A vector store that follows the saved Pinecone settings. Until they exist it does nothing:
    searches find nothing and indexing skips vectors."""

    def __init__(self, build: Builder, reader: SecretReader, defaults: Settings) -> None:
        self._store = RuntimeStore(lambda: current_config(reader, defaults), build, "Pinecone")

    def upsert(self, items: list[Evidence]) -> None:
        store = self._store.get()
        if store is not None:
            store.upsert(items)

    def delete_recording(self, recording_id: str, community_id: str) -> None:
        store = self._store.get()
        if store is not None:
            store.delete_recording(recording_id, community_id)

    def search(self, query: str, principal: Principal, limit: int = 20) -> list[Evidence]:
        store = self._store.get()
        return [] if store is None else store.search(query, principal, limit)


def _pinecone_builder(engine: Engine) -> Builder:
    def build(config: PineconeConfig) -> VectorStore:
        client = Pinecone(api_key=config.api_key)

        def hydrate_for(ids: list[str], principal: Principal) -> list[Evidence]:
            with session_scope(engine) as session:
                return hydrate(session, ids, principal, "vector")

        embedder = PineconeEmbedder(client, config.model)
        return PineconeVectorStore(
            client.Index(config.index), embedder, hydrate_for, config.dimension
        )

    return build


def vector_store_for(settings: Settings, engine: Engine) -> RuntimeVectorStore:
    """The vector store for this process. It works as soon as Pinecone is configured."""
    return RuntimeVectorStore(_pinecone_builder(engine), secrets_for(settings), settings)
