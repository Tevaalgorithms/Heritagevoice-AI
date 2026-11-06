"""Compile the question-answering workflow. Adapter exceptions intentionally propagate.

When both retrieval branches are needed they run side by side and meet again at the merge step,
so a question waits for the slower one instead of the sum. Authorization comes from the captured
trusted principal, never from model output. The caller supplies the agents (`Agents`), so tests
and the skeleton can inject fakes and the service injects the real ones.
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any, Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents import evidence_merger
from app.credits import Origin
from app.graph.state import StateUpdate, WorkflowState
from app.models.evidence import Route, Turn
from app.security.permissions import Principal, require_permitted


class Node(Protocol):
    """A graph node; the parameter name matches what LangGraph expects."""

    def __call__(self, state: WorkflowState) -> StateUpdate: ...


Retriever = Callable[[WorkflowState, Principal], StateUpdate]


@dataclass(frozen=True)
class Agents:
    """The steps of the workflow. Tests inject fakes; the service injects the real ones."""

    classify: Node
    hybrid: Retriever
    graph: Retriever
    verify: Node
    answer: Node
    rewrite: Callable[[str, list[Turn]], str] | None = None  # follow-up questions; optional
    # Asked just before an answer is returned: which cited sources can still be read?
    still_readable: Callable[[list[str], Principal], set[str]] | None = None
    # Where each cited recording came from (date, kind, and the credit when consent allows it).
    origins: Callable[[list[str]], dict[str, Origin]] | None = None


NEXT_STEPS = {
    Route.HYBRID: ["hybrid"],
    Route.GRAPH: ["graph"],
    Route.BOTH: ["hybrid", "graph"],  # run side by side
    Route.CLARIFY: ["stop"],
    Route.REFUSE: ["stop"],
}
RETRIEVAL_STEPS = ["hybrid", "graph"]
SUPERVISOR_TARGETS = [*RETRIEVAL_STEPS, "stop"]
MAX_RETRIES = 1
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


def route_after_supervisor(state: WorkflowState) -> list[str]:
    """The steps to run next; more than one means they run at the same time."""
    return NEXT_STEPS[state["route"]]


def run_answer(state: WorkflowState, principal: Principal, write: Node) -> StateUpdate:
    """The final gate: whatever the answer step cites, the reader must be allowed to read it."""
    return _authorized(write(state), "citations", principal)


def prepare_retry(state: WorkflowState) -> StateUpdate:
    """Keep what was found, then search once more with the verifier's suggested query."""
    found = state.get("earlier_evidence", []) + state.get("hybrid_evidence", [])
    found += state.get("graph_evidence", [])
    return {
        "earlier_evidence": found,
        "search_query": state.get("retry_query", ""),
        "retry_query": "",
        "retries": state.get("retries", 0) + 1,
        "hybrid_evidence": [],
        "graph_evidence": [],
    }


def route_after_verify(state: WorkflowState) -> str:
    """At most one retry, and only when the verifier asked for it."""
    wants_retry = bool(state.get("retry_query")) and state.get("retries", 0) < MAX_RETRIES
    return "retry" if wants_retry else "answer"


def _nodes(principal: Principal, agents: Agents) -> dict[str, Node]:
    hybrid = partial(run_retrieval, principal=principal, retrieve=agents.hybrid)
    graph = partial(run_retrieval, principal=principal, retrieve=agents.graph)
    return {
        "supervisor": agents.classify,
        "hybrid": partial(hybrid, key="hybrid_evidence"),
        "graph": partial(graph, key="graph_evidence"),
        "merge": partial(run_merge, principal=principal),
        "verify": agents.verify,
        "answer": partial(run_answer, principal=principal, write=agents.answer),
        "retry": prepare_retry,
        "stop": run_stop,
    }


def _wire(builder: StateGraph[WorkflowState]) -> None:
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges("supervisor", route_after_supervisor, SUPERVISOR_TARGETS)
    builder.add_conditional_edges("retry", route_after_supervisor, RETRIEVAL_STEPS)
    for source, target in (("hybrid", "merge"), ("graph", "merge"), ("merge", "verify")):
        builder.add_edge(source, target)
    builder.add_conditional_edges("verify", route_after_verify, ["retry", "answer"])
    builder.add_edge("answer", END)
    builder.add_edge("stop", END)


def build_workflow(
    principal: Principal,
    agents: Agents,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[WorkflowState]:
    builder = StateGraph(WorkflowState)
    for name, node in _nodes(principal, agents).items():
        builder.add_node(name, node)
    _wire(builder)
    return builder.compile(checkpointer=checkpointer)
