import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents.graph_extractor import (
    BATCH_SIZE,
    EXTRACTION,
    GraphExtractor,
    Proposal,
    Proposals,
    Source,
)
from app.db.repositories import GraphAssertionRepository
from app.db.session import session_scope
from app.db.tables import Base
from app.errors import ProviderError
from app.graph_extraction import ExtractDeps, extract_one, extract_recording
from app.models.job import Job, JobStatus
from app.models.records import Relation, ReviewState, Right
from app.models.transcript import Segment
from tests.index_helpers import TAMIL, published


class FakeRunner:
    """Answers each batch with the next prepared reply (or the same one every time)."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.inputs = []

    def invoke(self, inputs):
        self.inputs.append(inputs)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def proposal(subject="Amma", obj="the well", segment="s1", relation=Relation.MENTIONS, **extra):
    return Proposal(
        subject=subject, relation=relation, object=obj, segment_id=segment, confidence=0.6, **extra
    )


def source(segments=None, version=1):
    segments = segments or [
        Segment(segment_id="s1", start_s=0, end_s=1, text="x", speaker="Amma"),
        Segment(segment_id="s2", start_s=1, end_s=2, text="y"),
    ]
    return Source("r1", version, "v1", segments)


def extract(*proposals, src=None):
    runner = FakeRunner(Proposals(assertions=list(proposals)))
    return GraphExtractor(runner).extract(src or source())


def test_proposals_become_pending_assertions_with_the_speaker_and_policy():
    (found,) = extract(proposal())
    assert found.review_state is ReviewState.PENDING
    assert (found.asserted_by, found.policy_ref, found.transcript_version) == ("Amma", "v1", 1)
    assert (found.subject, found.object, found.supporting_segment_id) == ("Amma", "the well", "s1")


def test_a_segment_with_no_speaker_is_attributed_to_unknown():
    (found,) = extract(proposal(segment="s2"))
    assert found.asserted_by == "unknown"


@pytest.mark.parametrize(
    "bad",
    [
        proposal(segment="nope"),
        proposal(relation=Relation.SUPPORTED_BY),
        proposal(subject="   "),
        proposal(obj=""),
        proposal(subject="Well", obj=" well "),
        proposal(subject="x" * 201),
    ],
)
def test_invalid_proposals_are_dropped(bad):
    assert extract(bad) == []


def test_names_are_tidied_and_repeats_are_merged():
    found = extract(
        proposal(subject="  Amma  "), proposal(subject="amma"), proposal(obj="the   well")
    )
    assert len(found) == 1
    assert found[0].subject == "Amma"


def test_ids_are_stable_so_a_rerun_finds_the_same_assertions():
    assert extract(proposal())[0].id == extract(proposal())[0].id
    assert extract(proposal())[0].id != extract(proposal(), src=source(version=2))[0].id


def test_long_transcripts_are_read_in_batches():
    segments = [
        Segment(segment_id=f"s{n}", start_s=n, end_s=n + 1, text="t") for n in range(BATCH_SIZE + 1)
    ]
    runner = FakeRunner(Proposals())
    GraphExtractor(runner).extract(source(segments))
    assert len(runner.inputs) == 2
    assert len(json.loads(runner.inputs[0]["segments_json"])) == BATCH_SIZE


def test_an_unexpected_model_answer_is_a_provider_error():
    with pytest.raises(ProviderError) as caught:
        GraphExtractor(FakeRunner("not a Proposals object")).extract(source())
    assert caught.value.code == EXTRACTION


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'extract.db'}")
    Base.metadata.create_all(engine)
    return engine


def deps_for(engine, *proposals):
    runner = FakeRunner(Proposals(assertions=list(proposals)))
    return ExtractDeps(lambda: session_scope(engine), GraphExtractor(runner))


def seed(engine, **content):
    with session_scope(engine) as session:
        published(session, **content)


def stored(engine):
    with Session(engine) as session:
        return GraphAssertionRepository(session).with_state(ReviewState.PENDING)


def test_the_job_stores_pending_proposals_from_the_approved_transcript(engine):
    seed(engine, transcript=TAMIL)
    assert extract_one(deps_for(engine, proposal()), "r1") == 1
    assert [(a.subject, a.transcript_version) for a in stored(engine)] == [("Amma", 1)]


def test_running_again_adds_only_what_is_new_and_keeps_decisions(engine):
    seed(engine)
    deps = deps_for(engine, proposal())
    extract_one(deps, "r1")
    with session_scope(engine) as session:
        repo = GraphAssertionRepository(session)
        repo.decide(repo.with_state(ReviewState.PENDING)[0].id, ReviewState.REJECTED)
    assert extract_one(deps, "r1") == 0
    with Session(engine) as session:
        assert len(GraphAssertionRepository(session).with_state(ReviewState.REJECTED)) == 1


def test_pending_proposals_about_an_older_transcript_are_replaced(engine):
    seed(engine)
    extract_one(deps_for(engine, proposal(obj="old well")), "r1")
    with session_scope(engine) as session:
        repo = GraphAssertionRepository(session)
        assert repo.replace_pending("r1", 2, []) == 0
    assert stored(engine) == []


def job(recording_id):
    return Job(id="j", kind="extract_graph", status=JobStatus.QUEUED, recording_id=recording_id)


def test_without_the_ai_processing_right_nothing_is_sent_to_a_model(engine):
    seed(engine, consent={"rights": (Right.INDEXING,)})
    runner = FakeRunner(Proposals())
    deps = ExtractDeps(lambda: session_scope(engine), GraphExtractor(runner))
    outcome = extract_recording(job("r1"), deps)
    assert (outcome.status, outcome.error) == (JobStatus.FAILED, "consent")
    assert runner.inputs == []


def test_an_unknown_recording_fails_safely(engine):
    outcome = extract_recording(job("nope"), deps_for(engine))
    assert (outcome.status, outcome.error) == (JobStatus.FAILED, "missing")
