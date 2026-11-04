"""Pinecone vectors for semantic search, one namespace per community.

Pinecone is a derived, rebuildable index. It holds only vectors and IDs: no transcript text. A
search embeds the question, queries only the caller's own community namespaces, and then hands
the candidate IDs to `hydrate`, which reloads the passages from PostgreSQL and re-checks every
permission. Filters and namespaces narrow results; they are not the authorization boundary.
"""

import logging
from collections.abc import Callable, Iterable
from typing import Any

from app.errors import ProviderError
from app.models.evidence import Evidence
from app.models.groups import OPEN_COMMUNITY
from app.ports import Embedder
from app.security.permissions import COMMUNITY_PREFIX, Principal

logger = logging.getLogger("heritagevoice.pinecone")
EMBED_BATCH = 64
UPSERT_BATCH = 100
DELETE_BATCH = 500
CANDIDATE_FACTOR = 3
INDEX = "index"

Hydrate = Callable[[list[str], Principal], list[Evidence]]


def _batches(items: list[Any], size: int) -> Iterable[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _community(item: Evidence) -> str:
    labels = [g for g in item.access_groups if g.startswith(COMMUNITY_PREFIX)]
    if len(labels) != 1:
        raise ValueError("Evidence must belong to exactly one community")
    return labels[0].removeprefix(COMMUNITY_PREFIX)


class PineconeVectorStore:
    """Vector search in Pinecone: one namespace per community, no text stored there."""

    def __init__(self, index: Any, embedder: Embedder, hydrate: Hydrate, dimension: int) -> None:
        self._index = index
        self._embedder = embedder
        self._hydrate = hydrate
        self._dimension = dimension

    def upsert(self, items: list[Evidence]) -> None:
        by_namespace: dict[str, list[Evidence]] = {}
        for item in items:
            by_namespace.setdefault(_community(item), []).append(item)
        try:
            for namespace, group in by_namespace.items():
                self._upsert_namespace(namespace, group)
        except ProviderError:
            raise
        except Exception as error:
            logger.warning("vector upsert failed: %s", type(error).__name__)
            raise ProviderError("vector upsert failed", code=INDEX) from error

    def _upsert_namespace(self, namespace: str, items: list[Evidence]) -> None:
        vectors: list[dict[str, Any]] = []
        for batch in _batches(items, EMBED_BATCH):
            embedded = self._embedder.embed_passages([item.passage for item in batch])
            vectors.extend(
                self._vector(item, values) for item, values in zip(batch, embedded, strict=True)
            )
        for batch in _batches(vectors, UPSERT_BATCH):
            self._index.upsert(vectors=batch, namespace=namespace)

    def _vector(self, item: Evidence, values: list[float]) -> dict[str, Any]:
        if len(values) != self._dimension:
            raise ProviderError("embedding has the wrong dimension", code=INDEX)
        return {
            "id": item.evidence_id,
            "values": values,
            "metadata": {"recording_id": item.document_id, "version": item.document_version},
        }

    def delete_recording(self, recording_id: str, community_id: str) -> None:
        try:
            ids = [
                i
                for page in self._index.list(prefix=f"{recording_id}:", namespace=community_id)
                for i in page
            ]
            for batch in _batches(ids, DELETE_BATCH):
                self._index.delete(ids=batch, namespace=community_id)
        except Exception as error:
            logger.warning("vector delete failed: %s", type(error).__name__)
            raise ProviderError("vector delete failed", code=INDEX) from error

    def _candidate_ids(self, query: str, principal: Principal, limit: int) -> list[str]:
        vector = self._embedder.embed_query(query)
        scored: list[tuple[float, str]] = []
        for namespace in sorted(principal.communities | {OPEN_COMMUNITY}):
            response = self._index.query(
                vector=vector, top_k=limit * CANDIDATE_FACTOR, namespace=namespace
            )
            scored.extend((match["score"], match["id"]) for match in _matches(response))
        return [evidence_id for _, evidence_id in sorted(scored, key=lambda s: (-s[0], s[1]))]

    def search(self, query: str, principal: Principal, limit: int = 20) -> list[Evidence]:
        """Candidates by similarity from the reader's groups and the open-sharing space, then the
        evidence each reader may actually see, re-checked in PostgreSQL."""
        if not query.strip():
            return []
        ids = self._candidate_ids(query, principal, limit)
        return self._hydrate(ids[: limit * CANDIDATE_FACTOR], principal)[:limit]


def _matches(response: Any) -> list[dict[str, Any]]:
    raw = response["matches"] if isinstance(response, dict) else response.matches
    return [m if isinstance(m, dict) else {"id": m.id, "score": m.score} for m in raw]


class PineconeEmbedder:
    """Pinecone Inference embeddings (for example multilingual-e5-large)."""

    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        result = self._client.inference.embed(
            model=self._model,
            inputs=texts,
            parameters={"input_type": input_type, "truncate": "END"},
        )
        return [list(item["values"]) for item in result]

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for batch in _batches(texts, EMBED_BATCH):
            vectors.extend(self._embed(batch, "passage"))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "query")[0]
