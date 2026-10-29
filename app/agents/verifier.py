"""E01: semantic support verification is a required future integration."""

from app.config import IntegrationNotConfiguredError
from app.graph.state import StateUpdate, WorkflowState


def verify(state: WorkflowState) -> StateUpdate:
    raise IntegrationNotConfiguredError("Claim support verification is not implemented")
