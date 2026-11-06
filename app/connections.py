"""Connections: the approved relationships a reader may see, each with the words that say it.

A relationship is shown only if the passage that says it could be returned by a search for this
reader. The same gate decides: the recording is published, its consent still allows indexing, the
reader belongs to its community or it is public, and the assertion is about the transcript that is
approved now. Neo4j is not consulted; PostgreSQL, the source of truth, answers.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.agents.graph_rag import supporting_chunks
from app.credits import Origin, origins_in
from app.db.repositories import GraphAssertionRepository
from app.models.evidence import Evidence
from app.models.records import GraphAssertion, Relation
from app.qa import to_citation
from app.retrieval.evidence_store import hydrate
from app.security.permissions import Principal

CANDIDATE_FACTOR = 4
METHOD = "connections"


@dataclass(frozen=True)
class Connection:
    """One approved relationship, the passage that says it and where that passage is."""

    assertion_id: str
    subject: str
    relation: Relation
    object: str
    recording_id: str
    evidence_id: str
    passage: str
    start_s: float
    end_s: float
    notices: tuple[str, ...]
    origin: Origin | None


def _readable(
    session: Session, principal: Principal, chunk_of: dict[str, str]
) -> dict[str, Evidence]:
    """The passages these assertions rest on that this reader may read now, by evidence ID."""
    found = hydrate(session, sorted(set(chunk_of.values())), principal, METHOD)
    return {item.evidence_id: item for item in found}


def _readable_assertions(
    candidates: list[GraphAssertion], chunk_of: dict[str, str], readable: dict[str, Evidence]
) -> list[GraphAssertion]:
    return [a for a in candidates if chunk_of.get(a.id) in readable]


def find_connections(
    session: Session, principal: Principal, text: str, limit: int
) -> list[Connection]:
    """Approved relationships naming `text` (the newest if empty) that this reader may see."""
    candidates = GraphAssertionRepository(session).approved_matching(text, limit * CANDIDATE_FACTOR)
    chunk_of = supporting_chunks(session, {a.id: a for a in candidates})
    readable = _readable(session, principal, chunk_of)
    shown = _readable_assertions(candidates, chunk_of, readable)[:limit]
    origins = origins_in(session, [a.recording_id for a in shown])
    return [_connection(a, readable[chunk_of[a.id]], origins) for a in shown]


def _connection(
    assertion: GraphAssertion, evidence: Evidence, origins: dict[str, Origin]
) -> Connection:
    citation = to_citation(evidence)
    return Connection(
        assertion_id=assertion.id,
        subject=assertion.subject,
        relation=assertion.relation,
        object=assertion.object,
        recording_id=assertion.recording_id,
        evidence_id=citation.evidence_id,
        passage=citation.passage,
        start_s=citation.start_s,
        end_s=citation.end_s,
        notices=tuple(citation.notices),
        origin=origins.get(assertion.recording_id),
    )
