import pytest
from pydantic import ValidationError

from app.agents.evidence_merger import merge_evidence
from app.models.evidence import Evidence, QueryRequest
from app.retrieval.fusion import reciprocal_rank_fusion
from app.security.permissions import can_read, require_permitted


def test_default_deny_unknown_and_restricted_labels(principal, evidence):
    assert can_read(principal, evidence)
    for labels in ({"researcher"}, {"unknown"}, {"public", "unknown"}):
        restricted = evidence.model_copy(update={"access_groups": frozenset(labels)})
        assert not can_read(principal, restricted)
        with pytest.raises(PermissionError):
            require_permitted(principal, [restricted])


def test_empty_permissions_rejected(evidence):
    payload = evidence.model_dump()
    payload["access_groups"] = []
    with pytest.raises(ValidationError):
        Evidence.model_validate(payload)


def test_client_cannot_supply_role():
    with pytest.raises(ValidationError):
        QueryRequest.model_validate({"question": "Who?", "role": "researcher"})


def test_merge_preserves_all_provenance(evidence):
    graph = evidence.model_copy(
        update={
            "retrieval_methods": frozenset({"graph"}),
            "graph_paths": (("edge-1", "edge-2"),),
        }
    )
    merged = merge_evidence([evidence, graph])
    assert len(merged) == 1
    assert merged[0].retrieval_methods == {"bm25", "graph"}
    assert merged[0].graph_paths == (("edge-1", "edge-2"),)


@pytest.mark.parametrize(
    "change",
    [
        {"passage": "Changed text"},
        {"passage_hash": "different"},
        {"access_groups": frozenset({"researcher"})},
        {"evidence_id": "different"},
    ],
)
def test_same_chunk_cannot_change_identity_or_policy(evidence, change):
    with pytest.raises(ValueError):
        merge_evidence([evidence, evidence.model_copy(update=change)])


def test_conflicting_distinct_sources_remain_separate(evidence):
    other = evidence.model_copy(
        update={
            "document_id": "doc-2",
            "evidence_id": "ev-2",
            "passage": "Different account",
        }
    )
    assert len(merge_evidence([evidence, other])) == 2


def test_fusion_rewards_cross_retriever_agreement_without_duplicate_votes():
    result = dict(reciprocal_rank_fusion([["a", "a", "b"], ["b", "c"]]))
    assert result["a"] == pytest.approx(1 / 61)
    assert result["b"] == pytest.approx(1 / 63 + 1 / 61)
    assert next(iter(result)) == "b"
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["a"]], k=0)
