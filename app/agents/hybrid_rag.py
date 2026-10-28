"""H01: BM25 plus authorized vector retrieval and reciprocal rank fusion."""

from app.config import IntegrationNotConfigured
from app.graph.state import WorkflowState
from app.security.permissions import Principal


def retrieve(state: WorkflowState, principal: Principal) -> dict:
    raise IntegrationNotConfigured("Hybrid RAG adapter is not implemented")
