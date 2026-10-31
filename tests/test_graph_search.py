import pytest
from sqlalchemy import create_engine

from app.adapters.neo4j_reader import Neo4jGraphReader
from app.agents.graph_rag import GraphRetriever, supported_evidence
from app.agents.supervisor import GRAPH_UNAVAILABLE
from app.db.repositories import GraphAssertionRepository, VersionRepository
from app.db.session import session_scope
from app.db.tables import Base
from app.errors import ProviderError
from app.indexing import IndexDeps, index_one
from app.models.graph_path import GraphPath
from app.models.records import GraphAssertion, Relation, ReviewState, Subject, Visibility
from tests.helpers import person
from tests.index_helpers import published

MEMBER = person(communities=("c1",))
OUTSIDER = person(user_id="other", communities=("c2",))


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'search.db'}")
    Base.metadata.create_all(engine)
    return engine


def assertion(aid, segment="s1", state=ReviewState.APPROVED, version=1):
    return GraphAssertion(
        id=aid,
        recording_id="r1",
        subject="Amma",
        relation=Relation.MENTIONS,
        object="the well",
        asserted_by="speaker",
        review_state=state,
        supporting_segment_id=segment,
        transcript_version=version,
        confidence=0.5,
        policy_ref="v1",
    )


def seed(engine, assertions, **content):
    with session_scope(engine) as session:
        published(session, **content)
        GraphAssertionRepository(session).add_many(assertions)
    index_one(IndexDeps(lambda: session_scope(engine)), "r1")


def run(engine, paths, principal=MEMBER):
    with session_scope(engine) as session:
        return supported_evidence(session, paths, principal)


def path(*ids):
    steps = ("Amma", "MENTIONS", "the well")
    return GraphPath(assertion_ids=tuple(ids), steps=steps)


def test_an_approved_current_assertion_becomes_evidence_with_its_path(engine):
    seed(engine, [assertion("a1")])
    (item,) = run(engine, [path("a1")])
    assert item.graph_paths == (("Amma", "MENTIONS", "the well"),)
    assert item.retrieval_methods == {"graph"}
    assert item.passage.startswith("கோடையில்")


@pytest.mark.parametrize("state", [ReviewState.PENDING, ReviewState.REJECTED])
def test_an_assertion_that_is_not_approved_is_never_used(engine, state):
    seed(engine, [assertion("a1", state=state)])
    assert run(engine, [path("a1")]) == []


def test_an_assertion_about_an_older_transcript_is_never_used(engine):
    seed(engine, [assertion("a1", version=1)])
    with session_scope(engine) as session:
        VersionRepository(session).set_status("r1", Subject.TRANSCRIPT, 1, "superseded")
    assert run(engine, [path("a1")]) == []


def test_an_unknown_or_unsupported_segment_is_dropped(engine):
    seed(engine, [assertion("a1", segment="nope")])
    assert run(engine, [path("a1"), path("ghost")]) == []


def test_someone_outside_the_community_gets_nothing_from_a_private_recording(engine):
    seed(engine, [assertion("a1")])
    assert run(engine, [path("a1")], OUTSIDER) == []


def test_a_public_recording_can_be_reached_by_others(engine):
    seed(engine, [assertion("a1")], visibility=Visibility.PUBLIC)
    assert len(run(engine, [path("a1")], OUTSIDER)) == 1


def test_a_path_with_one_bad_edge_is_dropped_whole(engine):
    seed(engine, [assertion("a1"), assertion("a2", segment="nope")])
    assert run(engine, [path("a1", "a2")]) == []
    assert len(run(engine, [path("a1")])) == 1


def test_the_same_passage_found_by_two_paths_keeps_both_paths(engine):
    seed(engine, [assertion("a1")])
    other = GraphPath(assertion_ids=("a1",), steps=("the well", "MENTIONS", "Amma"))
    (item,) = run(engine, [path("a1"), other])
    assert len(item.graph_paths) == 2


class Reader:
    def __init__(self, paths=None, error=None):
        self.paths_found, self.error, self.asked = paths or [], error, []

    def paths(self, question, communities, limit):
        self.asked.append((question, communities, limit))
        if self.error:
            raise self.error
        return self.paths_found


def state():
    return {"question": "How is Amma linked to the well?"}


def retriever(engine, reader):
    return GraphRetriever(lambda: session_scope(engine), lambda: reader)


def test_the_retriever_asks_for_the_readers_own_communities_only(engine):
    seed(engine, [assertion("a1")])
    reader = Reader([path("a1")])
    update = retriever(engine, reader)(state(), MEMBER)
    assert len(update["graph_evidence"]) == 1
    assert reader.asked[0][1] == frozenset({"c1"})


def test_without_neo4j_the_graph_branch_warns_and_finds_nothing(engine):
    assert retriever(engine, None)(state(), MEMBER) == {
        "graph_evidence": [],
        "warnings": [GRAPH_UNAVAILABLE],
    }


def test_a_neo4j_failure_becomes_a_warning_not_an_error(engine):
    reader = Reader(error=ProviderError("down", code="graph"))
    update = retriever(engine, reader)(state(), MEMBER)
    assert update == {"graph_evidence": [], "warnings": [GRAPH_UNAVAILABLE]}


class Driver:
    def __init__(self, records=None, fail=False):
        self.records, self.fail, self.calls = records or [], fail, []

    def execute_query(self, query, parameters):
        if self.fail:
            raise RuntimeError("secret detail")
        self.calls.append((query, parameters))
        return self.records, None, None


def test_the_reader_passes_the_question_as_a_parameter_with_the_readers_scope():
    driver = Driver(
        [{"ids": ["a1", "a2"], "names": ["A", "B", "C"], "relations": ["MENTIONS", "DESCRIBES"]}]
    )
    found = Neo4jGraphReader(driver).paths(
        "who is A? '}) DETACH DELETE", frozenset({"c2", "c1"}), 5
    )
    assert found == [
        GraphPath(assertion_ids=("a1", "a2"), steps=("A", "MENTIONS", "B", "DESCRIBES", "C"))
    ]
    query, parameters = driver.calls[0]
    assert "DETACH" not in query
    assert parameters["question"].endswith("DETACH DELETE")
    assert (parameters["communities"], parameters["limit"]) == (["c1", "c2"], 5)


def test_reader_failures_become_provider_errors_without_their_text():
    with pytest.raises(ProviderError) as caught:
        Neo4jGraphReader(Driver(fail=True)).paths("q", frozenset(), 5)
    assert "secret" not in str(caught.value)
