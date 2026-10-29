import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.adapters.pinecone_store import PineconeVectorStore
from app.db.repositories import (
    ChunkRepository,
    ConsentRepository,
    NewVersion,
    RecordingRepository,
    VersionRepository,
)
from app.db.session import session_scope
from app.db.tables import Base, JobRow
from app.fakes import FakeEmbedder, FakePineconeIndex
from app.index_rebuild import rebuild_all
from app.index_sync import drop_index
from app.indexing import (
    INDEX_KIND,
    UNINDEX_KIND,
    IndexDeps,
    IndexRefusedError,
    index_one,
    index_recording,
    unindex_recording,
)
from app.models.index import ChunkKind
from app.models.job import Job, JobStatus
from app.models.records import Recording, RecordingStatus, Right, Subject, VersionStatus
from app.models.transcript import Segment
from app.retrieval.evidence_store import hydrate
from app.retrieval.search import lexical_evidence
from app.review import DecisionInput, EditInput, decide, edit_draft, publish
from app.revocation import revoke_consent
from app.security.permissions import community_label
from tests.helpers import person
from tests.index_helpers import ENGLISH, TAMIL, add_consent, published


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'index.db'}")
    Base.metadata.create_all(engine)
    return engine


def sessions(engine):
    return lambda: session_scope(engine)


def deps_with_vectors(engine, index=None):
    index = index or FakePineconeIndex()

    def hydrate_for(ids, principal):
        with session_scope(engine) as session:
            return hydrate(session, ids, principal, "vector")

    store = PineconeVectorStore(index, FakeEmbedder(), hydrate_for, dimension=64)
    return IndexDeps(sessions(engine), store), index, store


def setup(engine, **kwargs):
    with session_scope(engine) as session:
        return published(session, **kwargs)


def chunks(engine, recording_id="r1"):
    with Session(engine) as session:
        return ChunkRepository(session).get_many(
            ChunkRepository(session).ids_for_recording(recording_id)
        )


def search(engine, principal, query, limit=20):
    with Session(engine) as session:
        return lexical_evidence(session, principal, query, limit)


def test_a_published_recording_is_chunked_with_exact_audio_references(engine):
    setup(engine)
    assert index_one(IndexDeps(sessions(engine)), "r1") == 2
    transcript, translation = chunks(engine)
    assert (transcript.kind, transcript.version, transcript.language) == (
        ChunkKind.TRANSCRIPT,
        1,
        "ta",
    )
    assert transcript.evidence_id == "r1:transcript:v1:c0"
    assert (transcript.segment_ids, transcript.start_s, transcript.end_s) == (
        ("s1", "s2"),
        0.0,
        9.0,
    )
    assert (translation.kind, translation.language) == (ChunkKind.TRANSLATION, "en")


def test_a_translation_of_a_different_transcript_version_is_not_indexed(engine):
    setup(engine, translation=None)
    with session_scope(engine) as session:
        versions = VersionRepository(session)
        versions.add_draft(NewVersion("r1", Subject.TRANSLATION, ENGLISH, "system", 7))
        versions.set_status("r1", Subject.TRANSLATION, 1, VersionStatus.APPROVED)
    assert index_one(IndexDeps(sessions(engine)), "r1") == 1


@pytest.mark.parametrize(
    ("prepare", "code"),
    [
        (
            lambda s: RecordingRepository(s).set_status("r1", RecordingStatus.REVIEW),
            "not_published",
        ),
        (
            lambda s: RecordingRepository(s).set_status("r1", RecordingStatus.REVOKED),
            "not_published",
        ),
        (lambda s: ConsentRepository(s).revoke("consent-1"), "consent"),
    ],
    ids=["in-review", "revoked", "consent-revoked"],
)
def test_content_that_must_not_be_indexed_is_refused(engine, prepare, code):
    setup(engine)
    with session_scope(engine) as session:
        prepare(session)
    with pytest.raises(IndexRefusedError) as refusal:
        index_one(IndexDeps(sessions(engine)), "r1")
    assert refusal.value.code == code
    assert chunks(engine) == []


def test_unknown_recordings_and_missing_indexing_consent_are_refused(engine):
    with pytest.raises(IndexRefusedError, match="missing"):
        index_one(IndexDeps(sessions(engine)), "nope")
    with session_scope(engine) as session:
        add_consent(session, "consent-x", rights=[Right.PLAYBACK])
        published(session, "r2", consent_id="consent-x")
    with pytest.raises(IndexRefusedError, match="consent"):
        index_one(IndexDeps(sessions(engine)), "r2")


def test_a_recording_without_an_approved_transcript_is_refused(engine):
    with session_scope(engine) as session:
        published(session, "r3")
        VersionRepository(session).set_status("r3", Subject.TRANSCRIPT, 1, VersionStatus.REJECTED)
    with pytest.raises(IndexRefusedError, match="not_approved"):
        index_one(IndexDeps(sessions(engine)), "r3")


def test_keyword_search_finds_exact_tamil_and_english_terms(engine):
    setup(engine)
    index_one(IndexDeps(sessions(engine)), "r1")
    me = person(communities=("c1",))
    (tamil,) = search(engine, me, "ஏற்றம்")
    assert tamil.chunk_id == "transcript:0"
    assert tamil.retrieval_methods == {"bm25"}
    assert tamil.access_groups == {community_label("c1")}
    assert tamil.locator == "audio:r1?t=0.0-9.0"
    (english,) = search(engine, me, "lever")
    assert english.chunk_id == "translation:0"


def test_a_natural_question_matches_chunks_that_share_a_word(engine):
    setup(engine)
    index_one(IndexDeps(sessions(engine)), "r1")
    found = search(engine, person(), "How did villagers share water when rain was scarce?")
    assert [e.chunk_id for e in found] == ["translation:0"]


def test_a_chunk_can_only_be_found_by_members_of_its_community(engine):
    setup(engine)
    index_one(IndexDeps(sessions(engine)), "r1")
    assert search(engine, person(communities=("c2",)), "ஏற்றம்") == []
    assert search(engine, person(communities=()), "ஏற்றம்") == []
    assert len(search(engine, person(communities=("c1", "c2")), "ஏற்றம்")) == 1


def test_empty_questions_find_nothing(engine):
    setup(engine)
    index_one(IndexDeps(sessions(engine)), "r1")
    assert search(engine, person(), "   ") == []
    assert search(engine, person(), "?!...") == []


def test_results_respect_the_limit(engine):
    with session_scope(engine) as session:
        for n in range(5):
            published(session, f"r{n}", consent_id="consent-1")
    for n in range(5):
        index_one(IndexDeps(sessions(engine)), f"r{n}")
    assert len(search(engine, person(), "water", limit=3)) == 3


def test_an_older_approved_version_is_never_returned(engine):
    setup(engine)
    index_one(IndexDeps(sessions(engine)), "r1")
    new = [Segment(segment_id="s1", start_s=0.0, end_s=4.0, text="முற்றிலும் புதிய உரை")]
    with session_scope(engine) as session:
        versions = VersionRepository(session)
        versions.add_draft(NewVersion("r1", Subject.TRANSCRIPT, new, "editor"))
        versions.set_status("r1", Subject.TRANSCRIPT, 2, VersionStatus.APPROVED)
    assert search(engine, person(), "ஏற்றம்") == []  # stale chunk, not yet reindexed
    index_one(IndexDeps(sessions(engine)), "r1")
    assert [e.document_version for e in search(engine, person(), "புதிய")] == ["v2"]
    assert search(engine, person(), "ஏற்றம்") == []


def test_revoking_a_consent_removes_keyword_results_at_once_and_queues_the_clean_up(engine):
    setup(engine)
    index_one(IndexDeps(sessions(engine)), "r1")
    with session_scope(engine) as session:
        revoke_consent(session, "consent-1")
    assert chunks(engine) == []
    assert search(engine, person(), "ஏற்றம்") == []
    with Session(engine) as session:
        kinds = {j.kind for j in _jobs(session)}
    assert UNINDEX_KIND in kinds


def _jobs(session):
    return list(session.scalars(select(JobRow)))


def test_a_correction_after_publishing_removes_results_until_it_is_approved_again(engine):
    setup(engine, recording_id="r1")
    index_one(IndexDeps(sessions(engine)), "r1")
    with session_scope(engine) as session:
        recording = RecordingRepository(session).get("r1")
        edit_draft(session, recording, EditInput(Subject.TRANSCRIPT, 1, {"s1": "திருத்தம்"}, "ed"))
    assert search(engine, person(), "ஏற்றம்") == []
    with Session(engine) as session:
        assert RecordingRepository(session).get("r1").status == RecordingStatus.REVIEW
        assert UNINDEX_KIND in {j.kind for j in _jobs(session)}


def test_publishing_queues_an_index_job_that_makes_the_content_searchable(engine):
    with session_scope(engine) as session:
        add_consent(session)
        RecordingRepository(session).create(
            Recording(
                id="r1",
                community_id="c1",
                uploader_id="up",
                language="ta",
                consent_id="consent-1",
                status=RecordingStatus.REVIEW,
            )
        )
        versions = VersionRepository(session)
        versions.add_draft(NewVersion("r1", Subject.TRANSCRIPT, TAMIL, "system"))
    with session_scope(engine) as session:
        recording = RecordingRepository(session).get("r1")
        decide(session, recording, DecisionInput(Subject.TRANSCRIPT, 1, True), "rev")
        publish(session, recording)
    with Session(engine) as session:
        (job,) = [j for j in _jobs(session) if j.kind == INDEX_KIND]
    assert search(engine, person(), "ஏற்றம்") == []  # not searchable until the job has run
    deps = IndexDeps(sessions(engine))
    outcome = index_recording(
        Job(id=job.id, kind=INDEX_KIND, status=JobStatus.PROCESSING, recording_id="r1"), deps
    )
    assert outcome.status == JobStatus.PUBLISHED
    assert len(search(engine, person(), "ஏற்றம்")) == 1


def test_a_refused_index_job_fails_with_a_safe_code(engine):
    setup(engine)
    with session_scope(engine) as session:
        RecordingRepository(session).set_status("r1", RecordingStatus.REVIEW)
    job = Job(id="j", kind=INDEX_KIND, status=JobStatus.PROCESSING, recording_id="r1")
    outcome = index_recording(job, IndexDeps(sessions(engine)))
    assert (outcome.status, outcome.error) == (JobStatus.FAILED, "not_published")


def vector_count(index, namespace="c1"):
    return index.count(namespace)


def test_vectors_go_to_the_communitys_own_namespace_only(engine):
    setup(engine, recording_id="r1", community="c1")
    setup(engine, recording_id="r2", community="c2", consent_id="consent-2")
    deps, index, _ = deps_with_vectors(engine)
    index_one(deps, "r1")
    index_one(deps, "r2")
    assert (index.count("c1"), index.count("c2")) == (2, 2)
    assert all(i.startswith("r1:") for i in index.namespaces["c1"])
    assert all(i.startswith("r2:") for i in index.namespaces["c2"])


def test_vector_search_is_isolated_between_communities(engine):
    setup(engine, recording_id="r1", community="c1")
    setup(engine, recording_id="r2", community="c2", consent_id="consent-2")
    deps, _, store = deps_with_vectors(engine)
    index_one(deps, "r1")
    index_one(deps, "r2")
    mine = store.search("ஏற்றம் தண்ணீர்", person(communities=("c1",)))
    assert {e.document_id for e in mine} == {"r1"}
    assert {e.retrieval_methods == {"vector"} for e in mine} == {True}
    assert store.search("ஏற்றம் தண்ணீர்", person(communities=("c3",))) == []
    both = store.search("ஏற்றம் தண்ணீர்", person(communities=("c1", "c2")))
    assert {e.document_id for e in both} == {"r1", "r2"}


def test_a_stale_vector_cannot_return_content_after_revocation(engine):
    setup(engine)
    deps, index, store = deps_with_vectors(engine)
    index_one(deps, "r1")
    assert vector_count(index) == 2
    with session_scope(engine) as session:
        revoke_consent(session, "consent-1")  # the vectors are still in the index
    assert vector_count(index) == 2
    assert store.search("ஏற்றம் தண்ணீர்", person()) == []


def test_the_clean_up_job_removes_the_vectors(engine):
    setup(engine)
    deps, index, _ = deps_with_vectors(engine)
    index_one(deps, "r1")
    with session_scope(engine) as session:
        drop_index(session, "r1")
    job = Job(id="j", kind=UNINDEX_KIND, status=JobStatus.PROCESSING, recording_id="r1")
    assert unindex_recording(job, deps).status == JobStatus.PUBLISHED
    assert vector_count(index) == 0
    assert unindex_recording(job, deps).status == JobStatus.PUBLISHED  # safe to repeat
    missing = Job(id="j2", kind=UNINDEX_KIND, status=JobStatus.PROCESSING, recording_id="nope")
    assert unindex_recording(missing, deps).error == "missing"


def test_reindexing_replaces_the_old_vectors(engine):
    setup(engine)
    deps, index, _ = deps_with_vectors(engine)
    index_one(deps, "r1")
    index_one(deps, "r1")
    assert vector_count(index) == 2


def test_rebuild_reindexes_published_recordings_and_removes_leftovers(engine):
    setup(engine, recording_id="r1")
    setup(engine, recording_id="r2")
    deps, index, _ = deps_with_vectors(engine)
    index_one(deps, "r1")
    index_one(deps, "r2")
    with session_scope(engine) as session:
        RecordingRepository(session).set_status("r2", RecordingStatus.REVOKED)
    result = rebuild_all(deps)
    assert (result.indexed, result.removed) == (1, 1)
    assert chunks(engine, "r2") == []
    assert [i.split(":")[0] for i in index.namespaces["c1"]] == ["r1", "r1"]


def test_rebuild_with_nothing_published_is_a_no_op(engine):
    assert rebuild_all(IndexDeps(sessions(engine))).indexed == 0
