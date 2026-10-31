import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.auth import current_principal, get_session_factory
from app.api.main import app
from app.db.repositories import GraphAssertionRepository
from app.db.session import session_scope
from app.db.tables import AuditLogRow, Base, JobRow
from app.models.records import GraphAssertion, Relation, ReviewState
from app.security.roles import Role
from tests.helpers import person
from tests.index_helpers import published

ADMIN = person(Role.ADMIN, user_id="admin-1", communities=())


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'review.db'}")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def client(engine):
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    app.dependency_overrides[current_principal] = lambda: ADMIN
    yield TestClient(app)
    app.dependency_overrides.clear()


def act_as(principal):
    app.dependency_overrides[current_principal] = lambda: principal


def assertion(aid="a1", state=ReviewState.PENDING, version=1, **fields):
    values = {
        "id": aid,
        "recording_id": "r1",
        "subject": "Amma",
        "relation": Relation.MENTIONS,
        "object": "the well",
        "asserted_by": "speaker-1",
        "review_state": state,
        "supporting_segment_id": "s1",
        "transcript_version": version,
        "confidence": 0.5,
        "policy_ref": "v1",
    }
    return GraphAssertion(**{**values, **fields})


@pytest.fixture
def seeded(engine):
    with session_scope(engine) as session:
        published(session)
        GraphAssertionRepository(session).add_many(
            [assertion("a1"), assertion("a2", ReviewState.APPROVED), assertion("old", version=9)]
        )


def decide(client, aid="a1", **body):
    return client.post(f"/v1/graph/assertions/{aid}/decision", json={"approved": True, **body})


def state_of(engine, aid):
    with Session(engine) as session:
        return GraphAssertionRepository(session).get(aid)


def test_pending_proposals_are_listed_with_the_words_they_came_from(client, seeded):
    listed = client.get("/v1/graph/assertions").json()
    first = next(item for item in listed if item["id"] == "a1")
    assert (first["subject"], first["relation"], first["object"]) == (
        "Amma",
        "MENTIONS",
        "the well",
    )
    assert first["passage"].startswith("கோடையில்")
    assert (first["start_s"], first["end_s"]) == (0.0, 4.0)


def test_the_list_can_be_filtered_by_state(client, seeded):
    approved = client.get("/v1/graph/assertions?state=approved").json()
    assert [a["id"] for a in approved] == ["a2"]


def test_approving_queues_a_graph_refresh_and_is_audited_by_id(client, engine, seeded):
    response = decide(client)
    assert response.json() == {"id": "a1", "review_state": "approved"}
    assert state_of(engine, "a1").review_state is ReviewState.APPROVED
    with Session(engine) as session:
        assert [j.kind for j in session.scalars(select(JobRow))] == ["project_graph"]
        (entry,) = session.scalars(select(AuditLogRow))
    assert (entry.action, entry.target) == ("graph:approved", "graph:a1")


def test_rejecting_keeps_it_out_of_the_graph(client, engine, seeded):
    assert decide(client, approved=False).json()["review_state"] == "rejected"
    assert state_of(engine, "a1").review_state is ReviewState.REJECTED


def test_a_correction_is_saved_before_approval(client, engine, seeded):
    decide(client, edit={"subject": "Amma Lakshmi", "relation": "DESCRIBES"})
    saved = state_of(engine, "a1")
    assert (saved.subject, saved.relation, saved.object) == (
        "Amma Lakshmi",
        Relation.DESCRIBES,
        "the well",
    )


@pytest.mark.parametrize(
    "edit",
    [{"subject": ""}, {"object": "x" * 201}, {"relation": "SUPPORTED_BY"}, {"relation": "NOPE"}],
)
def test_bad_corrections_are_refused(client, seeded, edit):
    assert decide(client, edit=edit).status_code == 422


def test_a_correction_cannot_link_something_to_itself(client, seeded):
    response = decide(client, edit={"object": " amma "})
    assert (response.status_code, response.json()["detail"]["code"]) == (422, "invalid_edit")


def test_a_proposal_about_an_older_transcript_cannot_be_approved(client, seeded):
    response = decide(client, "old")
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "stale_version")
    assert decide(client, "old", approved=False).status_code == 200


def test_unknown_proposals_are_404(client, seeded):
    assert decide(client, "nope").status_code == 404


def test_only_admins_review(client, seeded):
    act_as(person(Role.MEMBER))
    assert client.get("/v1/graph/assertions").status_code == 403
    assert decide(client).status_code == 403
    act_as(person(Role.REVIEWER))
    assert client.get("/v1/graph/assertions").status_code == 403


def test_an_admin_cannot_approve_their_own_upload(client, engine, seeded):
    act_as(person(Role.ADMIN, user_id="uploader", communities=()))
    assert decide(client).status_code == 403
    assert state_of(engine, "a1").review_state is ReviewState.PENDING
