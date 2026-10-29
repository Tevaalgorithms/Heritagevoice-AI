"""G02: parameterized, allowlisted, sourced traversal with a two-hop maximum."""

from app.config import IntegrationNotConfiguredError
from app.graph.state import StateUpdate, WorkflowState
from app.security.permissions import Principal


def retrieve(state: WorkflowState, principal: Principal) -> StateUpdate:
    raise IntegrationNotConfiguredError("GraphRAG adapter is not implemented")
