"""R01: structured classification; no model/provider has been selected yet."""

from app.config import IntegrationNotConfigured
from app.graph.state import WorkflowState


def classify(state: WorkflowState) -> dict:
    raise IntegrationNotConfigured("Supervisor classification is not implemented")
