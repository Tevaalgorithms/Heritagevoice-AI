"""E01: semantic support verification is a required future integration."""

from app.config import IntegrationNotConfigured
from app.graph.state import WorkflowState


def verify(state: WorkflowState) -> dict:
    raise IntegrationNotConfigured("Claim support verification is not implemented")
