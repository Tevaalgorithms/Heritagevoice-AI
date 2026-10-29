"""S4: the whole shape works end to end with fakes, and nothing leaks along the way."""

import pytest

from app.errors import ProviderError
from app.fakes import fake_agents
from app.graph.workflow import Agents, build_workflow
from app.models.job import JobStatus
from app.security.permissions import Principal, can_read
from app.skeleton import DEMO_PRINCIPAL, Skeleton

QUESTION = "What did the elder say about seasonal wells?"


@pytest.fixture
def skeleton():
    return Skeleton()


def test_ingestion_produces_a_reviewable_draft(skeleton):
    state = skeleton.ingest("rec-1")
    assert state["status"] == JobStatus.REVIEW
    assert [s.segment_id for s in state["translations"]] == ["s1", "s2"]


def test_draft_is_never_searchable(skeleton):
    skeleton.ingest("rec-1")
    result = skeleton.ask(QUESTION)
    assert result["status"] == "insufficient_evidence"
    assert result["citations"] == []


def test_unapproved_recording_cannot_be_published(skeleton):
    draft = skeleton.ingest("rec-1")
    with pytest.raises(PermissionError):
        skeleton.publish(draft, approved=False)
    assert skeleton.ask(QUESTION)["citations"] == []


def test_approved_recording_gives_a_cited_answer(skeleton):
    skeleton.publish(skeleton.ingest("rec-1"), approved=True)
    result = skeleton.ask(QUESTION)
    assert result["status"] == "answered"
    cited_ids = {c.evidence_id for c in result["citations"]}
    assert cited_ids == {"rec-1:s1:v1"}
    assert all(f"[{cid}]" in result["answer"] for cid in cited_ids)


def test_vector_and_graph_hits_merge_into_one_source(skeleton):
    skeleton.publish(skeleton.ingest("rec-1"), approved=True)
    (citation,) = skeleton.ask(QUESTION)["citations"]
    assert citation.retrieval_methods == {"vector", "graph"}
    assert citation.graph_paths


def test_revoked_item_never_appears(skeleton):
    items = skeleton.publish(skeleton.ingest("rec-1"), approved=True)
    skeleton.revoke(items)
    assert skeleton.ask(QUESTION)["status"] == "insufficient_evidence"


def test_restricted_item_is_invisible_to_a_public_user(skeleton):
    items = skeleton.publish(skeleton.ingest("rec-1"), approved=True)
    skeleton.vector.upsert(
        [
            items[0].model_copy(
                update={"evidence_id": "x", "access_groups": frozenset({"researcher"})}
            )
        ]
    )
    result = skeleton.ask(QUESTION)
    assert "x" not in {c.evidence_id for c in result["citations"]}


def test_no_node_receives_evidence_outside_the_principal_scope(skeleton):
    skeleton.publish(skeleton.ingest("rec-1"), approved=True)
    skeleton.vector.upsert([_restricted(skeleton)])
    seen = []

    def spy_verify(state):
        seen.extend(state["evidence"])
        return skeleton.agents.verify(state)

    agents = Agents(**{**skeleton.agents.__dict__, "verify": spy_verify})
    build_workflow(DEMO_PRINCIPAL, agents=agents).invoke({"question": QUESTION})
    assert seen
    assert all(can_read(DEMO_PRINCIPAL, item) for item in seen)


def test_researcher_sees_what_a_public_user_cannot(skeleton):
    skeleton.publish(skeleton.ingest("rec-1"), approved=True)
    skeleton.vector.upsert([_restricted(skeleton)])
    researcher = Principal(user_id="r", groups=frozenset({"researcher"}), policy_version="v1")
    ids = {c.evidence_id for c in skeleton.ask(QUESTION, researcher)["citations"]}
    assert ids == {"restricted"}


def test_asr_failure_is_an_explicit_failed_state():
    class BrokenTranscriber:
        def transcribe(self, audio, language):
            raise ProviderError("timeout")

    state = Skeleton(BrokenTranscriber()).ingest("rec-1")
    assert (state["status"], state["error"]) == (JobStatus.FAILED, "asr")
    assert "translations" not in state


def test_fake_agents_can_be_swapped_without_touching_the_graph(skeleton, principal):
    agents = fake_agents(skeleton.vector, skeleton.graph)
    assert build_workflow(principal, agents=agents) is not None


def _restricted(skeleton):
    base = skeleton.vector.search("seasonal wells", DEMO_PRINCIPAL)[0]
    return base.model_copy(
        update={"evidence_id": "restricted", "access_groups": frozenset({"researcher"})}
    )
