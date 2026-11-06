"""Answer relationship questions from the reviewed knowledge graph.

Neo4j only suggests paths. Every edge of a path is then re-checked against PostgreSQL: the
assertion must still be approved, made about the transcript that is approved now, and the passage
that says it must still be readable by this person (published, consent, community or public). A
path with any edge that fails is dropped whole, so the graph can never show more than the text
could. What is kept is returned as ordinary evidence, with the path that led to it.
"""

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy.orm import Session

from app.agents.supervisor import GRAPH_UNAVAILABLE
from app.db.repositories import ChunkRepository, GraphAssertionRepository, VersionRepository
from app.errors import ProviderError
from app.graph.state import StateUpdate, WorkflowState
from app.models.evidence import Evidence
from app.models.graph_path import GraphPath
from app.models.records import GraphAssertion, ReviewState, Subject
from app.ports import GraphReader
from app.retrieval.evidence_store import hydrate
from app.security.permissions import Principal

logger = logging.getLogger("heritagevoice.agents")
PATH_LIMIT = 30
MAX_EVIDENCE = 8
METHOD = "graph"
SessionFactory = Callable[[], AbstractContextManager[Session]]
ReaderSource = Callable[[], GraphReader | None]


def _is_current(session: Session, assertion: GraphAssertion) -> int | None:
    """The approved transcript version this assertion is about, or None if it no longer counts."""
    transcript = VersionRepository(session).approved(assertion.recording_id, Subject.TRANSCRIPT)
    approved = assertion.review_state is ReviewState.APPROVED
    if transcript is None or not approved or transcript.version != assertion.transcript_version:
        return None
    return transcript.version


def supporting_chunks(session: Session, assertions: dict[str, GraphAssertion]) -> dict[str, str]:
    """For each still-valid approved assertion, the passage that says it."""
    found: dict[str, str] = {}
    for assertion in assertions.values():
        version = _is_current(session, assertion)
        if version is None:
            continue
        index = ChunkRepository(session).segment_index(assertion.recording_id, version)
        if assertion.supporting_segment_id in index:
            found[assertion.id] = index[assertion.supporting_segment_id]
    return found


def _kept(path: GraphPath, chunk_of: dict[str, str], readable: dict[str, Evidence]) -> bool:
    """A path stands only if every edge has a passage this person may read."""
    return all(chunk_of.get(a) in readable for a in path.assertion_ids)


def _collect(
    paths: list[GraphPath], chunk_of: dict[str, str], readable: dict[str, Evidence]
) -> list[Evidence]:
    """Evidence for the kept paths, each carrying the paths that led to it."""
    routes: dict[str, list[tuple[str, ...]]] = {}
    for path in paths:
        if _kept(path, chunk_of, readable):
            for assertion_id in path.assertion_ids:
                routes.setdefault(chunk_of[assertion_id], []).append(path.steps)
    return [
        readable[evidence_id].model_copy(update={"graph_paths": tuple(dict.fromkeys(steps))})
        for evidence_id, steps in routes.items()
    ]


def supported_evidence(
    session: Session, paths: list[GraphPath], principal: Principal
) -> list[Evidence]:
    """Turn candidate paths into evidence this person may read, dropping everything else."""
    ids = sorted({a for path in paths for a in path.assertion_ids})
    assertions = GraphAssertionRepository(session).get_many(ids)
    chunk_of = supporting_chunks(session, assertions)
    shown = hydrate(session, sorted(set(chunk_of.values())), principal, METHOD)
    readable = {item.evidence_id: item for item in shown}
    return _collect(paths, chunk_of, readable)[:MAX_EVIDENCE]


class GraphRetriever:
    """The graph branch of the question workflow."""

    def __init__(self, sessions: SessionFactory, reader: ReaderSource) -> None:
        self._sessions = sessions
        self._reader = reader

    def __call__(self, state: WorkflowState, principal: Principal) -> StateUpdate:
        reader = self._reader()
        if reader is None:
            return {"graph_evidence": [], "warnings": [GRAPH_UNAVAILABLE]}
        try:
            paths = reader.paths(state["question"], principal.communities, PATH_LIMIT)
        except ProviderError:
            return {"graph_evidence": [], "warnings": [GRAPH_UNAVAILABLE]}
        with self._sessions() as session:
            return {"graph_evidence": supported_evidence(session, paths, principal)}
