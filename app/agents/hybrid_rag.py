"""Hybrid retrieval: keyword search and meaning-based search, fused and trimmed.

`HybridRetriever` is the node the question graph calls. It does no ranking of its own: it asks each
search for up to 20 candidates (the reader's permissions are applied inside both searches), fuses
them with reciprocal rank fusion, and keeps the 5 to 8 passages worth sending on. If the vector
search is unavailable the node carries on with keyword results and records a warning, instead of
failing the whole question.
"""

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy.orm import Session

from app.config import IntegrationNotConfiguredError
from app.graph.state import StateUpdate, WorkflowState
from app.models.evidence import Evidence
from app.ports import VectorStore
from app.retrieval.fusion import CANDIDATES_PER_BRANCH, fuse_branches
from app.retrieval.query import normalize_query
from app.retrieval.search import lexical_evidence
from app.retrieval.selection import DEFAULT_LIMITS, SelectionLimits, select_passages
from app.security.permissions import Principal

logger = logging.getLogger("heritagevoice.retrieval")
SessionFactory = Callable[[], AbstractContextManager[Session]]
VECTOR_UNAVAILABLE = "vector_search_unavailable"


class HybridRetriever:
    """Finds the passages that may answer a question, for one reader."""

    def __init__(
        self,
        sessions: SessionFactory,
        vectors: VectorStore | None = None,
        limits: SelectionLimits = DEFAULT_LIMITS,
    ) -> None:
        self._sessions = sessions
        self._vectors = vectors
        self._limits = limits

    def __call__(self, state: WorkflowState, principal: Principal) -> StateUpdate:
        question = state["question"]
        meaning, warnings = self._meaning(question, principal)
        hits = fuse_branches({"bm25": self._keyword(question, principal), "vector": meaning})
        update: StateUpdate = {
            "hybrid_evidence": [hit.evidence for hit in select_passages(hits, self._limits)]
        }
        if warnings:
            update["warnings"] = warnings
        return update

    def _keyword(self, question: str, principal: Principal) -> list[Evidence]:
        """Keyword results for the question as typed and each of its spelling variants, merged."""
        with self._sessions() as session:
            per_variant = {
                variant: lexical_evidence(session, principal, variant, CANDIDATES_PER_BRANCH)
                for variant in normalize_query(question).variants
            }
        return [hit.evidence for hit in fuse_branches(per_variant)][:CANDIDATES_PER_BRANCH]

    def _meaning(self, question: str, principal: Principal) -> tuple[list[Evidence], list[str]]:
        """Vector results, or none plus a warning if the service failed. Never raises."""
        if self._vectors is None:
            return [], []
        try:
            return self._vectors.search(question, principal, CANDIDATES_PER_BRANCH), []
        except (
            Exception
        ) as error:  # an outside service: log its type only, keep the keyword results
            logger.warning("vector search failed: %s", type(error).__name__)
            return [], [VECTOR_UNAVAILABLE]


def retrieve(state: WorkflowState, principal: Principal) -> StateUpdate:
    """The default node, used until the service wires in a `HybridRetriever` with a database."""
    raise IntegrationNotConfiguredError("Hybrid retrieval is not wired to a database yet")
