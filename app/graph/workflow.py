"""Compile the agent skeleton. Adapter exceptions intentionally propagate.

Both retrieval branches run serially initially; the plan allows parallelization later.
Authorization comes from the captured trusted principal, never from model output.
The API does not expose this graph until identity, ownership and adapters are ready.
"""

from langgraph.graph import END, START, StateGraph

from app.agents import answer_agent, evidence_merger, graph_rag, hybrid_rag, supervisor, verifier
from app.graph.state import WorkflowState
from app.models.evidence import Route
from app.security.permissions import Principal, require_permitted


def build_workflow(principal: Principal, checkpointer=None):
    def hybrid(state: WorkflowState) -> dict:
        result = hybrid_rag.retrieve(state, principal)
        require_permitted(principal, result.get("hybrid_evidence", []))
        return result

    def graph(state: WorkflowState) -> dict:
        result = graph_rag.retrieve(state, principal)
        require_permitted(principal, result.get("graph_evidence", []))
        return result

    def safe_merge(state: WorkflowState) -> dict:
        result = evidence_merger.merge(state)
        require_permitted(principal, result["evidence"])
        return result

    def stop(state: WorkflowState) -> dict:
        if state["route"] == Route.CLARIFY:
            return {"status": "clarify", "answer": "Please clarify the person, place or event."}
        return {"status": "refused", "answer": "This request cannot be answered."}

    builder = StateGraph(WorkflowState)
    for name, node in (
        ("supervisor", supervisor.classify),
        ("hybrid", hybrid),
        ("graph", graph),
        ("merge", safe_merge),
        ("verify", verifier.verify),
        ("answer", answer_agent.synthesize),
        ("stop", stop),
    ):
        builder.add_node(name, node)
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        lambda s: s["route"],
        {
            Route.HYBRID: "hybrid",
            Route.GRAPH: "graph",
            Route.BOTH: "hybrid",
            Route.CLARIFY: "stop",
            Route.REFUSE: "stop",
        },
    )
    builder.add_conditional_edges(
        "hybrid",
        lambda s: "graph" if s["route"] == Route.BOTH else "merge",
        {"graph": "graph", "merge": "merge"},
    )
    builder.add_edge("graph", "merge")
    builder.add_edge("merge", "verify")
    builder.add_edge("verify", "answer")
    builder.add_edge("answer", END)
    builder.add_edge("stop", END)
    return builder.compile(checkpointer=checkpointer)
