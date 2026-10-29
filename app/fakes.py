"""In-memory ports for tests and the walking skeleton. No network, deterministic output."""

from app.models.evidence import Evidence
from app.models.transcript import Segment
from app.security.permissions import Principal, can_read


def _matches(query: str, item: Evidence) -> bool:
    return any(word in item.passage.lower() for word in query.lower().split())


class FakeVectorStore:
    def __init__(self) -> None:
        self._items: dict[str, Evidence] = {}

    def upsert(self, items: list[Evidence]) -> None:
        self._items.update({item.evidence_id: item for item in items})

    def delete(self, evidence_ids: list[str]) -> None:
        for evidence_id in evidence_ids:
            self._items.pop(evidence_id, None)

    def search(self, query: str, principal: Principal, limit: int = 20) -> list[Evidence]:
        hits = [i for i in self._items.values() if can_read(principal, i) and _matches(query, i)]
        return hits[:limit]


class FakeGraphStore:
    def __init__(self, items: list[Evidence] | None = None) -> None:
        self._items = items or []

    def traverse(self, query: str, principal: Principal, max_hops: int = 2) -> list[Evidence]:
        return [i for i in self._items if can_read(principal, i) and _within(i, max_hops)]


def _within(item: Evidence, max_hops: int) -> bool:
    return all(len(path) <= max_hops for path in item.graph_paths)


class FakeTranscriber:
    def __init__(self, segments: list[Segment]) -> None:
        self._segments = segments

    def transcribe(self, audio: bytes, language: str) -> list[Segment]:
        return list(self._segments)


class FakeTranslator:
    def translate(self, segments: list[Segment], target_language: str) -> list[Segment]:
        return [s.model_copy(update={"text": f"[{target_language}] {s.text}"}) for s in segments]
