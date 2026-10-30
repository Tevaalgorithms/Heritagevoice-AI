"""In-memory ports for tests and the walking skeleton. No network, deterministic output."""

import re
import zlib

from app.graph.state import StateUpdate, WorkflowState
from app.graph.workflow import Agents
from app.models.evidence import Claim, Evidence, Route
from app.models.transcript import Segment
from app.ports import GraphStore, VectorStore
from app.retrieval.tokenize import tokens
from app.security.permissions import Principal, can_read
from app.security.roles import Role


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def _matches(query: str, item: Evidence) -> bool:
    return bool(_words(query) & _words(item.passage))


class FakeVectorStore:
    """In-memory vector store for tests and the local demo."""

    def __init__(self) -> None:
        self._items: dict[str, Evidence] = {}

    def upsert(self, items: list[Evidence]) -> None:
        self._items.update({item.evidence_id: item for item in items})

    def delete(self, evidence_ids: list[str]) -> None:
        for evidence_id in evidence_ids:
            self._items.pop(evidence_id, None)

    def delete_recording(self, recording_id: str, community_id: str) -> None:
        self.delete([i for i, item in self._items.items() if item.document_id == recording_id])

    def search(self, query: str, principal: Principal, limit: int = 20) -> list[Evidence]:
        hits = [i for i in self._items.values() if can_read(principal, i) and _matches(query, i)]
        return hits[:limit]


class FakeGraphStore:
    """In-memory graph store for tests and the local demo."""

    def __init__(self, items: list[Evidence] | None = None) -> None:
        self._items = items or []

    def add(self, items: list[Evidence]) -> None:
        self._items.extend(items)

    def delete(self, evidence_ids: list[str]) -> None:
        self._items = [i for i in self._items if i.evidence_id not in evidence_ids]

    def traverse(self, query: str, principal: Principal, max_hops: int = 2) -> list[Evidence]:
        return [i for i in self._items if _visible(i, query, principal, max_hops)]


def _visible(item: Evidence, query: str, principal: Principal, max_hops: int) -> bool:
    return can_read(principal, item) and _matches(query, item) and _within(item, max_hops)


def _within(item: Evidence, max_hops: int) -> bool:
    return all(len(path) <= max_hops for path in item.graph_paths)


class FakeTranscriber:
    """A speech-to-text stand-in that returns fixed segments."""

    def __init__(self, segments: list[Segment]) -> None:
        self._segments = segments

    def transcribe(self, audio_key: str, language: str) -> list[Segment]:
        return list(self._segments)


class FakeTranslator:
    """A translator stand-in that returns fixed text."""

    def translate(self, segments: list[Segment], target_language: str) -> list[Segment]:
        return [s.model_copy(update={"text": f"[{target_language}] {s.text}"}) for s in segments]


def fake_verify(state: WorkflowState) -> StateUpdate:
    """Every retrieved passage supports a claim made of its own text."""
    evidence = state.get("evidence", [])
    claims = [
        Claim(text=e.passage, evidence_ids=[e.evidence_id], verdict="supported") for e in evidence
    ]
    return {"claims": claims}


def _abstain() -> StateUpdate:
    answer = "Not enough approved evidence."
    return {"status": "insufficient_evidence", "answer": answer, "citations": []}


def _cited(claim: Claim) -> str:
    return f"{claim.text} [{claim.evidence_ids[0]}]"


def _supported(state: WorkflowState) -> list[Claim]:
    return [c for c in state.get("claims", []) if c.verdict == "supported"]


def _citations(state: WorkflowState, claims: list[Claim]) -> list[Evidence]:
    by_id = {e.evidence_id: e for e in state.get("evidence", [])}
    return [by_id[c.evidence_ids[0]] for c in claims]


def fake_answer(state: WorkflowState) -> StateUpdate:
    """Quote supported claims with their citation markers; abstain when there are none."""
    claims = _supported(state)
    if not claims:
        return _abstain()
    text = " ".join(_cited(c) for c in claims)
    return {"status": "answered", "answer": text, "citations": _citations(state, claims)}


def fake_agents(vector: VectorStore, graph: GraphStore, route: Route = Route.BOTH) -> Agents:
    def classify(state: WorkflowState) -> StateUpdate:
        return {"route": route}

    def hybrid(state: WorkflowState, principal: Principal) -> StateUpdate:
        return {"hybrid_evidence": vector.search(state["question"], principal)}

    def graph_branch(state: WorkflowState, principal: Principal) -> StateUpdate:
        return {"graph_evidence": graph.traverse(state["question"], principal)}

    return Agents(classify, hybrid, graph_branch, fake_verify, fake_answer)


class FakeIdentityProvider:
    """Records what was asked of the identity service."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def invite_user(self, email: str, role: Role) -> str:
        sub = f"sub-{len(self.calls) + 1}"
        self.calls.append(("invite", email, role.value, sub))
        return sub

    def set_role(self, sub: str, role: Role) -> None:
        self.calls.append(("set_role", sub, role.value))

    def disable_user(self, sub: str) -> None:
        self.calls.append(("disable", sub))


class FakeAudioStore:
    """In-memory audio storage for tests."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    def get(self, key: str) -> bytes:
        return self.objects[key][0]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class FakeEmbedder:
    """Deterministic bag-of-words vectors: texts that share words are close. No network."""

    def __init__(self, dimension: int = 64) -> None:
        self.dimension = dimension
        self.passage_calls = 0

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for word in set(tokens(text)):
            vector[zlib.crc32(word.encode()) % self.dimension] += 1.0
        return vector

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        self.passage_calls += 1
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


IdList = list[str]
IdPages = list[IdList]


class FakePineconeIndex:
    """In-memory stand-in for a Pinecone index with the same call shapes (namespaces, list)."""

    def __init__(self) -> None:
        self.namespaces: dict[str, dict[str, list[float]]] = {}

    def upsert(self, vectors: list[dict[str, object]], namespace: str) -> None:
        space = self.namespaces.setdefault(namespace, {})
        for vector in vectors:
            space[str(vector["id"])] = list(vector["values"])  # type: ignore[call-overload]

    def query(
        self, vector: list[float], top_k: int, namespace: str
    ) -> dict[str, list[dict[str, object]]]:
        space = self.namespaces.get(namespace, {})
        scored = [(_cosine(vector, v), i) for i, v in space.items()]
        best = sorted(scored, key=lambda s: (-s[0], s[1]))[:top_k]
        return {"matches": [{"id": i, "score": s} for s, i in best if s > 0]}

    def list(self, prefix: str, namespace: str) -> IdPages:
        ids = sorted(i for i in self.namespaces.get(namespace, {}) if i.startswith(prefix))
        return [ids] if ids else []

    def delete(self, ids: IdList, namespace: str) -> None:
        for vector_id in ids:
            self.namespaces.get(namespace, {}).pop(vector_id, None)

    def count(self, namespace: str) -> int:
        return len(self.namespaces.get(namespace, {}))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = (sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5)
    return dot / norm if norm else 0.0
