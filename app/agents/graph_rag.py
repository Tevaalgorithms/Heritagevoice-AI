"""G02: parameterized, allowlisted, sourced traversal with a two-hop maximum."""

from app.config import IntegrationNotConfigured
from app.graph.state import WorkflowState
from app.security.permissions import Principal


def retrieve(state: WorkflowState, principal: Principal) -> dict:
    raise IntegrationNotConfigured("GraphRAG adapter is not implemented")
