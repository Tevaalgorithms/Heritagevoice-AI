"""E01: synthesize only supported claims and validate the final answer."""

from app.config import IntegrationNotConfigured
from app.graph.state import WorkflowState


def synthesize(state: WorkflowState) -> dict:
    raise IntegrationNotConfigured("Answer synthesis and final validation are not implemented")
