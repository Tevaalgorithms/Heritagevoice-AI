"""Connections show only approved relationships whose passage the reader could find by searching."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.api.auth import current_principal, get_session_factory
from app.api.main import app
from app.api.public import get_limiter
from app.connections import find_connections
from app.db.repositories import ConsentRepository, GraphAssertionRepository, VersionRepository
from app.db.session import session_scope
from app.db.tables import Base
from app.indexing import IndexDeps, index_one
from app.models.credit import SourceKind
from app.models.records import (
    GraphAssertion,
    Relation,
    ReviewState,
    Right,
    Subject,
    Visibility,
    path_text,
)
from app.ratelimit import SlidingWindowLimiter
from tests.helpers import person
from tests.index_helpers import published

MEMBER = person(communities=("c1",))
OUTSIDER = person(user_id="other", communities=("c2",))
VISITOR = person(user_id="visitor", communities=())
ALL = tuple(Right)
NO_CREDIT = tuple(r for r in Right if r is not Right.ATTRIBUTION)


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'connections.db'}")
    Base.metadata.create_all(engine)
    return engine


def assertion(aid="a1", state=ReviewState.APPROVED, version=1, **fields):
    values = {
        "id": aid,
        "recording_id": "r1",
        "subject": "Amma",
        "relation": Relation.MENTIONS,
        "object": "the well",
        "asserted_by": "speaker",
        "review_state": state,
        "supporting_segment_id": "s1",
        "transcript_version": version,
        "confidence": 0.5,
        "policy_ref": "v1",
    }
    return GraphAssertion(**{**values, **fields})


def seed(engine, assertions=None, **content):
    with session_scope(engine) as session:
        published(session, **content)
        GraphAssertionRepository(session).add_many(assertions or [assertion()])
    index_one(IndexDeps(lambda: session_scope(engine)), "r1")


def found(engine, principal=MEMBER, text="", limit=20):
    with session_scope(engine) as session:
        return find_connections(session, principal, text, limit)


def test_an_approved_relationship_comes_with_the_words_that_say_it(engine):
    seed(engine)
    (connection,) = found(engine)
    assert (connection.subject, connection.relation, connection.object) == (
        "Amma",
        Relation.MENTIONS,
        "the well",
    )
    assert connection.passage.startswith("கோடையில்")
    assert (connection.start_s, connection.end_s) != (0, 0)
    assert connection.origin.added


@pytest.mark.parametrize("state", [ReviewState.PENDING, ReviewState.REJECTED])
def test_a_relationship_that_is_not_approved_is_never_shown(engine, state):
    seed(engine, [assertion(state=state)])
    assert found(engine) == []


def test_a_relationship_about_an_older_transcript_is_not_shown(engine):
    seed(engine)
    with session_scope(engine) as session:
        VersionRepository(session).set_status("r1", Subject.TRANSCRIPT, 1, "superseded")
    assert found(engine) == []


def test_a_member_of_another_community_cannot_see_a_community_only_relationship(engine):
    seed(engine)
    assert len(found(engine, MEMBER)) == 1
    assert found(engine, OUTSIDER) == []
    assert found(engine, VISITOR) == []


def test_a_public_relationship_is_visible_to_a_visitor_with_no_account(engine):
    seed(engine, visibility=Visibility.PUBLIC)
    assert len(found(engine, VISITOR)) == 1
    assert len(found(engine, OUTSIDER)) == 1


def test_a_withdrawn_consent_hides_the_relationship_at_once(engine):
    seed(engine, visibility=Visibility.PUBLIC)
    with session_scope(engine) as session:
        ConsentRepository(session).revoke("consent-1")
    assert found(engine, MEMBER) == []
    assert found(engine, VISITOR) == []


def test_public_needs_the_public_sharing_right_not_just_a_public_label(engine):
    no_public = tuple(r for r in Right if r is not Right.PUBLIC_SHARING)
    seed(engine, visibility=Visibility.PUBLIC, consent={"rights": no_public})
    assert found(engine, VISITOR) == []
    assert len(found(engine, MEMBER)) == 1


def test_searching_matches_either_side_ignoring_case_and_leaves_the_rest_out(engine):
    seed(
        engine,
        [
            assertion("a1"),
            assertion("a2", subject="the elephant", relation=Relation.TEACHES, object="humility"),
        ],
    )
    assert [c.assertion_id for c in found(engine, text="HUMILITY")] == ["a2"]
    assert [c.assertion_id for c in found(engine, text="amma")] == ["a1"]
    assert found(engine, text="nothing like this") == []
    assert len(found(engine)) == 2


def test_percent_and_underscore_in_a_search_match_themselves_only(engine):
    seed(engine)
    assert found(engine, text="%") == []
    assert found(engine, text="_") == []


def test_the_limit_is_respected(engine):
    seed(engine, [assertion(f"a{i}", object=f"thing {i}") for i in range(5)])
    assert len(found(engine, limit=3)) == 3


CREDITED = {
    "credit_name": "Amma Selvi",
    "source_kind": SourceKind.FAMILY,
    "source_note": "Jaffna",
}


def test_the_credit_travels_with_a_connection_when_the_consent_allows_crediting(engine):
    seed(engine, **CREDITED)
    credit = found(engine)[0].origin.credit
    assert (credit.name, credit.source_kind, credit.source_note) == (
        "Amma Selvi",
        SourceKind.FAMILY,
        "Jaffna",
    )


def test_without_the_attribution_right_the_connection_has_the_date_but_no_credit(engine):
    seed(engine, consent={"rights": NO_CREDIT}, **CREDITED)
    origin = found(engine)[0].origin
    assert origin.credit is None
    assert origin.added


def test_a_path_reads_as_a_sentence():
    assert path_text(("proverb", "TEACHES", "humility")) == "proverb teaches humility"
    assert path_text(("a", "MENTIONS", "b", "SPOKE_IN", "c")) == "a mentions b spoke in c"
    assert path_text(("a", "SURPRISE", "b")) == "a SURPRISE b"


# --- the endpoints ----------------------------------------------------------------------------


@pytest.fixture
def client(engine):
    seed(engine, visibility=Visibility.PUBLIC)
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    app.dependency_overrides[current_principal] = lambda: MEMBER
    app.dependency_overrides[get_limiter] = lambda: SlidingWindowLimiter(100, 60.0)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_the_signed_in_endpoint_returns_connections_with_their_source(client):
    body = client.get("/v1/connections").json()
    (item,) = body["items"]
    assert (item["subject"], item["relation"], item["object"]) == ("Amma", "MENTIONS", "the well")
    assert item["recording_id"] == "r1"
    assert item["passage"]
    assert item["added"]


def test_signing_in_is_required_for_the_signed_in_endpoint():
    app.dependency_overrides.clear()
    assert TestClient(app).get("/v1/connections").status_code in {401, 503}


def test_a_visitor_sees_public_connections_and_the_response_is_not_kept(client):
    response = client.get("/v1/public/connections", params={"q": "amma"})
    assert response.status_code == 200
    assert [i["object"] for i in response.json()["items"]] == ["the well"]
    assert response.headers["cache-control"] == "no-store"
    assert "noindex" in response.headers["x-robots-tag"]


def test_a_visitor_never_gets_a_private_connection(engine):
    seed(engine)  # community only
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    app.dependency_overrides[get_limiter] = lambda: SlidingWindowLimiter(100, 60.0)
    try:
        assert TestClient(app).get("/v1/public/connections").json() == {"items": []}
    finally:
        app.dependency_overrides.clear()


def test_a_visitor_asking_too_often_is_slowed_down(client):
    tight = SlidingWindowLimiter(1, 60.0)
    app.dependency_overrides[get_limiter] = lambda: tight
    assert client.get("/v1/public/connections").status_code == 200
    assert client.get("/v1/public/connections").status_code == 429


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 999}, {"q": "x" * 101}])
def test_bad_parameters_are_refused(client, params):
    assert client.get("/v1/connections", params=params).status_code == 422


def test_a_connection_can_be_searched_by_its_english_meaning(engine):
    seed(
        engine,
        [
            assertion(
                "a1", subject="பணிவு", object="யானை", object_en="elephant", subject_en="humility"
            )
        ],
    )
    assert [c.assertion_id for c in found(engine, text="Humility")] == ["a1"]
    assert [c.assertion_id for c in found(engine, text="பணிவு")] == ["a1"]
    assert found(engine, text="grandmother") == []


def test_a_connection_carries_its_english_meanings_and_the_english_translation(engine):
    seed(engine, [assertion("a1", subject_en="Amma", object_en="the well")])
    (connection,) = found(engine)
    assert (connection.subject_en, connection.object_en) == ("Amma", "the well")
    assert connection.translation.startswith("In summer we drew water")


def test_no_translation_is_shown_when_there_is_none_or_it_is_no_longer_current(engine):
    seed(engine, translation=None)
    assert found(engine)[0].translation == ""
    other = create_engine(f"sqlite:///{engine.url.database}.2")
    Base.metadata.create_all(other)
    seed(other)
    with session_scope(other) as session:
        VersionRepository(session).set_status("r1", Subject.TRANSLATION, 1, "superseded")
    (stale,) = found(other)
    assert stale.translation == ""
    assert stale.passage  # the original words are still shown
