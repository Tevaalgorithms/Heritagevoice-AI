"""Compile the agent skeleton. Adapter exceptions intentionally propagate.

Both retrieval branches run serially initially; the plan allows parallelization later.
Authorization comes from the captured trusted principal, never from model output.
The API does not expose this graph until identity, ownership and adapters are ready.
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any, Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents import answer_agent, evidence_merger, graph_rag, hybrid_rag, supervisor, verifier
from app.graph.state import StateUpdate, WorkflowState
from app.models.evidence import Route
from app.security.permissions import Principal, require_permitted


class Node(Protocol):
    """A graph node; the parameter name matches what LangGraph expects."""

    def __call__(self, state: WorkflowState) -> StateUpdate: ...


Retriever = Callable[[WorkflowState, Principal], StateUpdate]


@dataclass(frozen=True)
class Agents:
    """The model-backed steps. Tests and the skeleton inject fakes; production injects real ones."""

    classify: Node
    hybrid: Retriever
    graph: Retriever
    verify: Node
    answer: Node


def default_agents() -> Agents:
    """Resolve the agent modules at call time so tests can monkeypatch them."""
    return Agents(
        classify=supervisor.classify,
        hybrid=hybrid_rag.retrieve,
        graph=graph_rag.retrieve,
        verify=verifier.verify,
        answer=answer_agent.synthesize,
    )


SUPERVISOR_ROUTES = {
    Route.HYBRID: "hybrid",
    Route.GRAPH: "graph",
    Route.BOTH: "hybrid",
    Route.CLARIFY: "stop",
    Route.REFUSE: "stop",
}
SUPERVISOR_TARGETS = sorted(set(SUPERVISOR_ROUTES.values()))
STOP_MESSAGES = {
    Route.CLARIFY: ("clarify", "Please clarify the person, place or event."),
    Route.REFUSE: ("refused", "This request cannot be answered."),
}


def _authorized(result: StateUpdate, key: str, principal: Principal) -> StateUpdate:
    require_permitted(principal, result.get(key, []))
    return result


def run_retrieval(
    state: WorkflowState, principal: Principal, retrieve: Retriever, key: str
) -> StateUpdate:
    return _authorized(retrieve(state, principal), key, principal)


def run_merge(state: WorkflowState, principal: Principal) -> StateUpdate:
    return _authorized(evidence_merger.merge(state), "evidence", principal)


def run_stop(state: WorkflowState) -> StateUpdate:
    status, answer = STOP_MESSAGES[state["route"]]
    return {"status": status, "answer": answer}


def route_after_supervisor(state: WorkflowState) -> str:
    return SUPERVISOR_ROUTES[state["route"]]


def route_after_hybrid(state: WorkflowState) -> str:
    return "graph" if state["route"] == Route.BOTH else "merge"


def _nodes(principal: Principal, agents: Agents) -> dict[str, Node]:
    hybrid = partial(run_retrieval, principal=principal, retrieve=agents.hybrid)
    graph = partial(run_retrieval, principal=principal, retrieve=agents.graph)
    return {
        "supervisor": agents.classify,
        "hybrid": partial(hybrid, key="hybrid_evidence"),
        "graph": partial(graph, key="graph_evidence"),
        "merge": partial(run_merge, principal=principal),
        "verify": agents.verify,
        "answer": agents.answer,
        "stop": run_stop,
    }


def _wire(builder: StateGraph[WorkflowState]) -> None:
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges("supervisor", route_after_supervisor, SUPERVISOR_TARGETS)
    builder.add_conditional_edges("hybrid", route_after_hybrid, ["graph", "merge"])
    for source, target in (("graph", "merge"), ("merge", "verify"), ("verify", "answer")):
        builder.add_edge(source, target)
    builder.add_edge("answer", END)
    builder.add_edge("stop", END)


def build_workflow(
    principal: Principal,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    agents: Agents | None = None,
) -> CompiledStateGraph[WorkflowState]:
    builder = StateGraph(WorkflowState)
    for name, node in _nodes(principal, agents or default_agents()).items():
        builder.add_node(name, node)
    _wire(builder)
    return builder.compile(checkpointer=checkpointer)
