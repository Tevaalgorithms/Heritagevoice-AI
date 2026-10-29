"""Authorized keyword search: candidates from the index, then the eligibility gate."""

from sqlalchemy.orm import Session

from app.models.evidence import Evidence
from app.retrieval.evidence_store import hydrate
from app.retrieval.lexical import lexical_search
from app.security.permissions import Principal

CANDIDATE_FACTOR = 3


def lexical_evidence(
    session: Session, principal: Principal, query: str, limit: int = 20
) -> list[Evidence]:
    ids = lexical_search(session, query, principal.communities, limit * CANDIDATE_FACTOR)
    return hydrate(session, ids, principal, "bm25")[:limit]
