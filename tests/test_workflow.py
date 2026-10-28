import pytest

from app.agents import answer_agent, graph_rag, hybrid_rag, supervisor, verifier
from app.config import IntegrationNotConfigured
from app.graph.workflow import build_workflow
from app.models.evidence import Route


def test_default_graph_cannot_fabricate_an_answer(principal):
    with pytest.raises(IntegrationNotConfigured):
        build_workflow(principal).invoke({"question": "Who?"})


@pytest.mark.parametrize("route", [Route.CLARIFY, Route.REFUSE])
def test_safe_stop_skips_unconfigured_retrievers(monkeypatch, principal, route):
    monkeypatch.setattr(supervisor, "classify", lambda state: {"route": route})
    result = build_workflow(principal).invoke({"question": "Who?"})
    assert result["status"] == ("clarify" if route == Route.CLARIFY else "refused")
    assert "evidence" not in result


def test_both_routes_reach_merge_with_both_results(monkeypatch, principal, evidence):
    visited = []
    monkeypatch.setattr(supervisor, "classify", lambda state: {"route": Route.BOTH})

    def hybrid(state, trusted_principal):
        assert trusted_principal == principal
        visited.append("hybrid")
        return {"hybrid_evidence": [evidence]}

    def graph(state, trusted_principal):
        visited.append("graph")
        return {
            "graph_evidence": [
                evidence.model_copy(
                    update={
                        "retrieval_methods": frozenset({"graph"}),
                    }
                )
            ]
        }

    monkeypatch.setattr(hybrid_rag, "retrieve", hybrid)
    monkeypatch.setattr(graph_rag, "retrieve", graph)
    monkeypatch.setattr(verifier, "verify", lambda state: {"claims": []})
    monkeypatch.setattr(
        answer_agent,
        "synthesize",
        lambda state: {
            "status": "answered",
            "answer": "Synthetic test output",
        },
    )
    result = build_workflow(principal).invoke({"question": "Who?"})
    assert visited == ["hybrid", "graph"]
    assert len(result["evidence"]) == 1
    assert result["evidence"][0].retrieval_methods == {"bm25", "graph"}


def test_forbidden_retrieval_stops_before_verification(monkeypatch, principal, evidence):
    monkeypatch.setattr(supervisor, "classify", lambda state: {"route": Route.HYBRID})
    restricted = evidence.model_copy(update={"access_groups": frozenset({"researcher"})})
    monkeypatch.setattr(
        hybrid_rag,
        "retrieve",
        lambda state, principal: {
            "hybrid_evidence": [restricted],
        },
    )
    with pytest.raises(PermissionError):
        build_workflow(principal).invoke({"question": "Who?"})
