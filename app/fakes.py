"""In-memory ports for tests and the walking skeleton. No network, deterministic output."""

import re

from app.graph.state import StateUpdate, WorkflowState
from app.graph.workflow import Agents
from app.models.evidence import Claim, Evidence, Route
from app.models.transcript import Segment
from app.ports import GraphStore, VectorStore
from app.security.permissions import Principal, can_read
from app.security.roles import Role


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def _matches(query: str, item: Evidence) -> bool:
    return bool(_words(query) & _words(item.passage))


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
    def __init__(self, segments: list[Segment]) -> None:
        self._segments = segments

    def transcribe(self, audio: bytes, language: str) -> list[Segment]:
        return list(self._segments)


class FakeTranslator:
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
