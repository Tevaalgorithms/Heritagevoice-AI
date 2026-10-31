"""Decide how a question will be searched. It routes; it never grants or widens access."""

import logging
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from app.config import IntegrationNotConfiguredError
from app.errors import ProviderError
from app.graph.state import StateUpdate, WorkflowState
from app.models.evidence import Route
from app.ports import Invoker

logger = logging.getLogger("heritagevoice.agents")
SUPERVISOR_UNAVAILABLE = "supervisor_unavailable"
GRAPH_UNAVAILABLE = "graph_unavailable"
GRAPH_ROUTES = {Route.GRAPH, Route.BOTH}


class RouteDecision(BaseModel):
    """The model's choice of route for a question."""

    route: Route


class Supervisor:
    """Classifies a question. Without a model it searches the text, which is the safe default."""

    def __init__(self, runner: Invoker, graph_enabled: Callable[[], bool] = lambda: False) -> None:
        self._runner = runner
        self._graph_enabled = graph_enabled

    def __call__(self, state: WorkflowState) -> StateUpdate:
        try:
            decision = _decision(self._runner.invoke({"question": state["question"]}))
        except ProviderError:
            return {"route": Route.HYBRID, "warnings": [SUPERVISOR_UNAVAILABLE]}
        return self._available(decision.route)

    def _available(self, route: Route) -> StateUpdate:
        """Without a graph, relationship questions are answered from the text, with a warning."""
        if route in GRAPH_ROUTES and not self._graph_enabled():
            return {"route": Route.HYBRID, "warnings": [GRAPH_UNAVAILABLE]}
        return {"route": route}


def _decision(result: Any) -> RouteDecision:
    if not isinstance(result, RouteDecision):
        raise ProviderError("unexpected routing output", code="supervisor")
    return result


def classify(state: WorkflowState) -> StateUpdate:
    """The default node, used until the service wires in a `Supervisor` with a model."""
    raise IntegrationNotConfiguredError("Question routing is not wired to a model yet")
