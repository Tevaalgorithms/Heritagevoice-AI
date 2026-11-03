import threading

import pytest

from app.graph.workflow import Agents, build_workflow
from app.models.evidence import Route


def agents(**steps):
    """Agents that fail loudly unless a test supplies the step it expects to reach."""

    def unexpected(*args):
        raise AssertionError("this step should not run")

    defaults = {
        "classify": unexpected,
        "hybrid": unexpected,
        "graph": unexpected,
        "verify": unexpected,
        "answer": unexpected,
    }
    return Agents(**(defaults | steps))


@pytest.mark.parametrize("route", [Route.CLARIFY, Route.REFUSE])
def test_safe_stop_skips_the_retrievers(principal, route):
    workflow = build_workflow(principal, agents(classify=lambda state: {"route": route}))
    result = workflow.invoke({"question": "Who?"})
    assert result["status"] == ("clarify" if route == Route.CLARIFY else "refused")
    assert "evidence" not in result


def test_both_routes_reach_merge_with_both_results(principal, evidence):
    visited = []

    def hybrid(state, trusted_principal):
        assert trusted_principal == principal
        visited.append("hybrid")
        return {"hybrid_evidence": [evidence]}

    def graph(state, trusted_principal):
        visited.append("graph")
        methods = frozenset({"graph"})
        return {"graph_evidence": [evidence.model_copy(update={"retrieval_methods": methods})]}

    workflow = build_workflow(
        principal,
        agents(
            classify=lambda state: {"route": Route.BOTH},
            hybrid=hybrid,
            graph=graph,
            verify=lambda state: {"claims": []},
            answer=lambda state: {"status": "answered", "answer": "Synthetic test output"},
        ),
    )
    result = workflow.invoke({"question": "Who?"})
    assert sorted(visited) == ["graph", "hybrid"]
    assert len(result["evidence"]) == 1
    assert result["evidence"][0].retrieval_methods == {"bm25", "graph"}


def test_both_searches_run_at_the_same_time(principal, evidence):
    """Each search waits for the other to start; run one after the other they would time out."""
    meeting = threading.Barrier(2, timeout=5)

    def search(key):
        def run(state, who):
            meeting.wait()
            return {key: [evidence]}

        return run

    workflow = build_workflow(
        principal,
        agents(
            classify=lambda state: {"route": Route.BOTH},
            hybrid=search("hybrid_evidence"),
            graph=search("graph_evidence"),
            verify=lambda state: {"claims": []},
            answer=lambda state: {"status": "answered", "answer": "Synthetic test output"},
        ),
    )
    assert workflow.invoke({"question": "Who?"})["status"] == "answered"


def test_forbidden_retrieval_stops_before_verification(principal, evidence):
    restricted = evidence.model_copy(update={"access_groups": frozenset({"researcher"})})
    workflow = build_workflow(
        principal,
        agents(
            classify=lambda state: {"route": Route.HYBRID},
            hybrid=lambda state, trusted_principal: {"hybrid_evidence": [restricted]},
        ),
    )
    with pytest.raises(PermissionError):
        workflow.invoke({"question": "Who?"})
