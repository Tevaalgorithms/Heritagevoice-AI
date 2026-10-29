"""R01: structured classification; no model/provider has been selected yet."""

from app.config import IntegrationNotConfiguredError
from app.graph.state import StateUpdate, WorkflowState


def classify(state: WorkflowState) -> StateUpdate:
    raise IntegrationNotConfiguredError("Supervisor classification is not implemented")
