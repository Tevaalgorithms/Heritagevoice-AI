"""The vector store, following the Pinecone settings saved in the admin portal.

`RuntimeVectorStore` looks at the saved key, index, embedding model and dimension each time it is
used (the reader keeps them in memory for a few minutes). It builds the real Pinecone store the
first time they are all present, and builds a new one if any of them changes. Until Pinecone is
configured it does nothing: searches find nothing and indexing skips vectors, so keyword search
keeps working. Saving a key in the portal therefore needs no redeploy.
"""

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass

from pinecone import Pinecone
from sqlalchemy.engine import Engine

from app.adapters.pinecone_store import PineconeEmbedder, PineconeVectorStore
from app.config import Settings
from app.db.session import session_scope
from app.models.evidence import Evidence
from app.ports import VectorStore
from app.retrieval.evidence_store import hydrate
from app.secrets import SecretReader, secrets_for
from app.security.permissions import Principal

logger = logging.getLogger("heritagevoice.vectors")


@dataclass(frozen=True)
class PineconeConfig:
    """Everything needed to talk to Pinecone. Two configs are equal only if all fields match."""

    api_key: str
    index: str
    model: str
    dimension: int

    def fingerprint(self) -> tuple[str, str, str, int]:
        """Tells configs apart without keeping the key in a comparison or a log line."""
        digest = hashlib.sha256(self.api_key.encode()).hexdigest()[:12]
        return (digest, self.index, self.model, self.dimension)


Builder = Callable[[PineconeConfig], VectorStore]


def _text(reader: SecretReader, name: str) -> str | None:
    value = reader.get(name)
    return value.get_secret_value() if value else None


def _dimension(reader: SecretReader, default: int) -> int:
    raw = _text(reader, "EMBEDDING_DIMENSION")
    return int(raw) if raw and raw.isdigit() else default


def current_config(reader: SecretReader, defaults: Settings) -> PineconeConfig | None:
    """The saved settings, with the environment as defaults. None until key and index exist."""
    key, index = _text(reader, "PINECONE_API_KEY"), _text(reader, "PINECONE_INDEX")
    if not key or not index:
        return None
    model = _text(reader, "EMBEDDING_MODEL") or defaults.embedding_model
    return PineconeConfig(key, index, model, _dimension(reader, defaults.embedding_dimension))


class RuntimeVectorStore:
    """A vector store that rebuilds itself when the saved Pinecone settings change."""

    def __init__(self, build: Builder, reader: SecretReader, defaults: Settings) -> None:
        self._build = build
        self._reader = reader
        self._defaults = defaults
        self._built: tuple[tuple[str, str, str, int], VectorStore] | None = None

    def upsert(self, items: list[Evidence]) -> None:
        store = self._store()
        if store is not None:
            store.upsert(items)

    def delete_recording(self, recording_id: str, community_id: str) -> None:
        store = self._store()
        if store is not None:
            store.delete_recording(recording_id, community_id)

    def search(self, query: str, principal: Principal, limit: int = 20) -> list[Evidence]:
        store = self._store()
        return [] if store is None else store.search(query, principal, limit)

    def _store(self) -> VectorStore | None:
        config = current_config(self._reader, self._defaults)
        if config is None:
            return None
        if self._built is None or self._built[0] != config.fingerprint():
            self._built = self._rebuild(config)
        return self._built[1] if self._built else None

    def _rebuild(
        self, config: PineconeConfig
    ) -> tuple[tuple[str, str, str, int], VectorStore] | None:
        try:
            return config.fingerprint(), self._build(config)
        except Exception as error:  # a bad key or index: keyword search keeps working
            logger.warning("Pinecone could not be set up: %s", type(error).__name__)
            return None


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
