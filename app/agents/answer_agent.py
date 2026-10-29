"""E01: synthesize only supported claims and validate the final answer."""

from app.config import IntegrationNotConfiguredError
from app.graph.state import StateUpdate, WorkflowState


def synthesize(state: WorkflowState) -> StateUpdate:
    raise IntegrationNotConfiguredError("Answer synthesis and final validation are not implemented")
