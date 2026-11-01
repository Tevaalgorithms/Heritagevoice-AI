"""The retrieval node end to end: real database and permission gate, fake vector service."""

import pytest
from sqlalchemy import create_engine

from app.adapters.pinecone_store import PineconeVectorStore
from app.agents.hybrid_rag import VECTOR_UNAVAILABLE, HybridRetriever
from app.db.session import session_scope
from app.db.tables import Base
from app.fakes import FakeEmbedder, FakePineconeIndex
from app.indexing import IndexDeps, index_one
from app.models.records import Visibility
from app.retrieval.evidence_store import hydrate
from app.retrieval.selection import SelectionLimits
from tests.helpers import person
from tests.index_helpers import published

INSIDER = person(user_id="insider", communities=("c1",))
OUTSIDER = person(user_id="outsider", communities=("c9",))


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'hybrid.db'}")
    Base.metadata.create_all(engine)
    return engine


def sessions(engine):
    return lambda: session_scope(engine)


def vector_store(engine):
    def hydrate_for(ids, principal):
        with session_scope(engine) as session:
            return hydrate(session, ids, principal, "vector")

    return PineconeVectorStore(FakePineconeIndex(), FakeEmbedder(), hydrate_for, dimension=64)


def add(engine, store, recording_id="r1", community="c1", **options):
    with session_scope(engine) as session:
        published(session, recording_id, community, **options)
    index_one(IndexDeps(sessions(engine), store), recording_id)


def ask(retriever, principal, question):
    return retriever({"question": question}, principal)


def ids(update):
    return [e.document_id for e in update["hybrid_evidence"]]


def test_a_question_finds_the_passage_by_its_words(engine):
    store = vector_store(engine)
    add(engine, store)
    update = ask(HybridRetriever(sessions(engine), store), INSIDER, "shared the water")
    assert set(ids(update)) == {"r1"}  # the original and its translation are both from r1
    assert "warnings" not in update


def test_a_passage_found_by_both_searches_says_so(engine):
    store = vector_store(engine)
    add(engine, store)
    found = ask(HybridRetriever(sessions(engine), store), INSIDER, "shared the water")
    assert {"bm25", "vector"} in [set(e.retrieval_methods) for e in found["hybrid_evidence"]]
    assert len({e.evidence_id for e in found["hybrid_evidence"]}) == len(found["hybrid_evidence"])


def test_without_a_vector_service_keyword_search_still_answers_with_no_warning(engine):
    add(engine, vector_store(engine))
    update = ask(HybridRetriever(sessions(engine), None), INSIDER, "shared the water")
    assert set(ids(update)) == {"r1"}
    assert "warnings" not in update


class BrokenVectors:
    def search(self, query, principal, limit=20):
        raise TimeoutError("pinecone is down")


def test_a_failing_vector_service_becomes_a_warning_and_keyword_results_still_return(engine):
    add(engine, vector_store(engine))
    update = ask(HybridRetriever(sessions(engine), BrokenVectors()), INSIDER, "shared the water")
    assert set(ids(update)) == {"r1"}
    assert update["warnings"] == [VECTOR_UNAVAILABLE]


def test_the_warning_never_carries_the_providers_message(engine):
    add(engine, vector_store(engine))
    update = ask(HybridRetriever(sessions(engine), BrokenVectors()), INSIDER, "shared the water")
    assert "pinecone" not in str(update["warnings"]).lower()


def test_a_reader_outside_the_community_gets_nothing_from_either_search(engine):
    store = vector_store(engine)
    add(engine, store, visibility=Visibility.COMMUNITY)
    update = ask(HybridRetriever(sessions(engine), store), OUTSIDER, "shared the water")
    assert update["hybrid_evidence"] == []


def test_public_recordings_reach_outsiders_through_keyword_search(engine):
    store = vector_store(engine)
    add(engine, store, visibility=Visibility.PUBLIC)
    update = ask(HybridRetriever(sessions(engine), store), OUTSIDER, "shared the water")
    assert set(ids(update)) == {"r1"}
    methods = {m for e in update["hybrid_evidence"] for m in e.retrieval_methods}
    assert methods == {"bm25"}  # public recordings are not in an outsider's vector space


def test_a_spelling_variant_with_a_hidden_joiner_still_finds_the_passage(engine):
    store = vector_store(engine)
    add(engine, store)
    typed = "தண்‍ணீர்"  # the same word with a zero-width joiner typed inside it
    assert set(ids(ask(HybridRetriever(sessions(engine), None), INSIDER, typed))) == {"r1"}


def test_the_limits_apply_to_what_the_node_returns(engine):
    store = vector_store(engine)
    for index in range(5):
        add(engine, store, f"r{index}")
    limits = SelectionLimits(max_passages=3, per_recording=1)
    update = ask(HybridRetriever(sessions(engine), store, limits), INSIDER, "water")
    assert len(update["hybrid_evidence"]) == 3
    assert len(set(ids(update))) == 3  # one per recording


def test_an_empty_question_returns_nothing(engine):
    add(engine, vector_store(engine))
    assert ask(HybridRetriever(sessions(engine), None), INSIDER, "  ")["hybrid_evidence"] == []


def test_a_remedy_passage_carries_its_notice_and_other_kinds_do_not(engine):
    from app.models.records import REMEDY_NOTICE, HeritageKind  # noqa: PLC0415

    store = vector_store(engine)
    add(engine, store, "r-remedy", kind=HeritageKind.REMEDY)
    add(engine, store, "r-story", kind=HeritageKind.STORY)
    found = ask(HybridRetriever(sessions(engine), store), INSIDER, "water")["hybrid_evidence"]
    notices = {e.document_id: e.notices for e in found}
    assert notices["r-remedy"] == (REMEDY_NOTICE,)
    assert notices["r-story"] == ()
