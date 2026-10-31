import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.adapters.neo4j_graph import Neo4jProjection, entity_key
from app.db.repositories import GraphAssertionRepository, VersionRepository
from app.db.session import session_scope
from app.db.tables import Base
from app.errors import ProviderError
from app.fakes import FakeGraphProjection
from app.graph_projection import rebuild_graph
from app.indexing import IndexDeps, index_one, project_graph, remove_recording
from app.models.records import (
    GraphAssertion,
    Relation,
    ReviewState,
    Right,
    Subject,
    Visibility,
)
from app.revocation import revoke_consent
from tests.index_helpers import published


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'graph.db'}")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def graph():
    return FakeGraphProjection()


@pytest.fixture
def deps(engine, graph):
    return IndexDeps(lambda: session_scope(engine), None, graph)


def assertion(aid, state=ReviewState.APPROVED, version=1, recording="r1"):
    return GraphAssertion(
        id=aid,
        recording_id=recording,
        subject="Amma",
        relation=Relation.MENTIONS,
        object="the well",
        asserted_by="speaker-1",
        review_state=state,
        supporting_segment_id="s1",
        transcript_version=version,
        confidence=0.4,
        policy_ref="v1",
    )


def seed(engine, assertions, **content):
    with session_scope(engine) as session:
        published(session, **content)
        GraphAssertionRepository(session).add_many(assertions)


def test_only_approved_assertions_reach_the_graph(engine, deps, graph):
    seed(
        engine,
        [
            assertion("a1"),
            assertion("a2", ReviewState.PENDING),
            assertion("a3", ReviewState.REJECTED),
        ],
    )
    assert project_graph(deps, "r1") == 1
    community, visibility, written = graph.written["r1"]
    assert (community, visibility, [a.id for a in written]) == ("c1", Visibility.COMMUNITY, ["a1"])


def test_assertions_about_an_older_transcript_are_left_out(engine, deps):
    seed(engine, [assertion("old", version=1), assertion("new", version=2)])
    with session_scope(engine) as session:
        VersionRepository(session).set_status("r1", Subject.TRANSCRIPT, 1, "superseded")
    assert project_graph(deps, "r1") == 0


def test_a_recording_that_may_not_be_read_is_removed_from_the_graph(engine, deps, graph):
    seed(engine, [assertion("a1")])
    project_graph(deps, "r1")
    with session_scope(engine) as session:
        revoke_consent(session, "consent-1")
    assert project_graph(deps, "r1") == 0
    assert "r1" not in graph.written


def test_without_the_indexing_right_nothing_is_projected(engine, deps, graph):
    seed(engine, [assertion("a1")], consent={"rights": (Right.PLAYBACK,)})
    assert project_graph(deps, "r1") == 0
    assert graph.written == {}


def test_public_visibility_needs_the_public_sharing_consent(engine, deps, graph):
    seed(
        engine,
        [assertion("a1")],
        visibility=Visibility.PUBLIC,
        consent={"rights": (Right.INDEXING,)},
    )
    project_graph(deps, "r1")
    assert graph.written["r1"][1] is Visibility.COMMUNITY


def test_publishing_projects_and_removal_clears_it(engine, deps, graph):
    seed(engine, [assertion("a1")])
    index_one(deps, "r1")
    assert "r1" in graph.written
    assert remove_recording(deps, "r1") is True
    assert graph.written == {}


def test_without_a_graph_nothing_happens(engine):
    deps = IndexDeps(lambda: session_scope(engine))
    seed(engine, [assertion("a1")])
    assert project_graph(deps, "r1") == 0
    assert rebuild_graph(deps).projected == 0


def test_a_rebuild_projects_wanted_recordings_and_removes_leftovers(engine, deps, graph):
    seed(engine, [assertion("a1")])
    graph.replace_recording("gone", "c1", Visibility.COMMUNITY, [assertion("x", recording="gone")])
    result = rebuild_graph(deps)
    assert (result.projected, result.removed) == (1, 1)
    assert graph.recording_ids() == ["r1"]


def test_repository_review_decisions(engine):
    seed(engine, [assertion("a1", ReviewState.PENDING)])
    with Session(engine) as session:
        repo = GraphAssertionRepository(session)
        assert [a.id for a in repo.with_state(ReviewState.PENDING)] == ["a1"]
        assert repo.decide("a1", ReviewState.APPROVED) is True
        assert repo.decide("nope", ReviewState.APPROVED) is False
        assert repo.approved_for("r1")[0].id == "a1"
        assert repo.recording_ids_with_approved() == ["r1"]
        assert repo.delete_for_recording("r1") == 1


class FakeTransaction:
    def __init__(self, driver):
        self.driver = driver

    def run(self, query, parameters):
        self.driver.statements.append((query, parameters))
        return self

    def consume(self):
        return None


class FakeNeo4jSession:
    def __init__(self, driver):
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute_write(self, work):
        if self.driver.fail:
            raise RuntimeError("secret detail")
        self.driver.transactions += 1
        work(FakeTransaction(self.driver))


class Driver:
    def __init__(self, fail=False):
        self.statements = []
        self.queries = []
        self.transactions = 0
        self.fail = fail

    def session(self):
        return FakeNeo4jSession(self)

    def execute_query(self, query, parameters):
        if self.fail:
            raise RuntimeError("secret detail")
        self.queries.append(query)
        return [{"id": "r1"}], None, None


def test_neo4j_replace_is_one_transaction_with_parameters_and_a_fixed_relationship_type():
    driver = Driver()
    Neo4jProjection(driver).replace_recording("r1", "c1", Visibility.PUBLIC, [assertion("a1")])
    assert driver.transactions == 1
    removal, write = driver.statements
    assert removal[1] == {"recording_id": "r1"}
    query, parameters = write
    assert "[r:MENTIONS {assertion_id: row.assertion_id}]" in query
    assert (parameters["visibility"], parameters["community_id"]) == ("public", "c1")
    (row,) = parameters["rows"]
    assert (row["skey"], row["okey"]) == ("c1:amma", "c1:the well")
    assert "Amma" not in query


def test_many_assertions_cost_one_query_per_relationship_type():
    driver = Driver()
    many = [assertion(f"a{n}") for n in range(50)]
    many.append(assertion("d1").model_copy(update={"relation": Relation.DESCRIBES}))
    Neo4jProjection(driver).replace_recording("r1", "c1", Visibility.COMMUNITY, many)
    assert len(driver.statements) == 3  # removal, MENTIONS (50 rows), DESCRIBES (1 row)


def test_deleting_a_recording_is_one_scoped_statement():
    driver = Driver()
    Neo4jProjection(driver).delete_recording("r1")
    ((query, parameters),) = driver.statements
    assert parameters == {"recording_id": "r1"}
    assert "DELETE e" in query


def test_the_same_name_in_two_communities_is_two_nodes():
    assert entity_key("c1", "Amma") != entity_key("c2", "Amma")
    assert entity_key("c1", "  The   Well ") == entity_key("c1", "the well")


def test_neo4j_failures_become_provider_errors_without_their_text():
    with pytest.raises(ProviderError) as caught:
        Neo4jProjection(Driver(fail=True)).delete_recording("r1")
    assert "secret" not in str(caught.value)


def test_the_schema_is_created_with_a_uniqueness_rule():
    driver = Driver()
    Neo4jProjection(driver).ensure_schema()
    assert "REQUIRE e.key IS UNIQUE" in driver.queries[0]


def test_recordings_in_the_graph_are_listed():
    assert Neo4jProjection(Driver()).recording_ids() == ["r1"]
