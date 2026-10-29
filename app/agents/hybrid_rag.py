"""H01: BM25 plus authorized vector retrieval and reciprocal rank fusion."""

from app.config import IntegrationNotConfiguredError
from app.graph.state import StateUpdate, WorkflowState
from app.security.permissions import Principal


def retrieve(state: WorkflowState, principal: Principal) -> StateUpdate:
    raise IntegrationNotConfiguredError("Hybrid RAG adapter is not implemented")
