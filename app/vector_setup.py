"""Build the vector store from settings: Pinecone when configured, otherwise none."""

import logging

from pinecone import Pinecone
from sqlalchemy.engine import Engine

from app.adapters.pinecone_store import PineconeEmbedder, PineconeVectorStore
from app.config import Settings
from app.db.session import session_scope
from app.models.evidence import Evidence
from app.ports import VectorStore
from app.retrieval.evidence_store import hydrate
from app.security.permissions import Principal

logger = logging.getLogger("heritagevoice.vectors")


def vector_store_for(settings: Settings, engine: Engine) -> VectorStore | None:
    """Pinecone when a key and index are configured; otherwise keyword search only."""
    if settings.pinecone_api_key is None or not settings.pinecone_index:
        logger.warning("Pinecone is not configured; only keyword search is available")
        return None
    client = Pinecone(api_key=settings.pinecone_api_key.get_secret_value())

    def hydrate_for(ids: list[str], principal: Principal) -> list[Evidence]:
        with session_scope(engine) as session:
            return hydrate(session, ids, principal, "vector")

    embedder = PineconeEmbedder(client, settings.embedding_model)
    index = client.Index(settings.pinecone_index)
    return PineconeVectorStore(index, embedder, hydrate_for, settings.embedding_dimension)
