import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.auth import current_principal, get_session_factory
from app.api.main import app
from app.db.repositories import CommunityRepository, ConsentRepository, UserRepository
from app.db.session import session_scope
from app.db.tables import AuditLogRow, Base
from app.models.groups import slugify
from app.security.roles import Role
from tests.helpers import consent, person

ADMIN = person(Role.ADMIN, user_id="admin-1", communities=())
COORDINATOR = person(Role.REVIEWER, user_id="coord-1", communities=("my-family",))
MEMBER = person(Role.MEMBER, user_id="member-1", communities=("my-family",))


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'groups.db'}")
    Base.metadata.create_all(engine)
    with session_scope(engine) as session:
        users = UserRepository(session)
        users.create("admin-1", Role.ADMIN, frozenset())
        users.create("coord-1", Role.REVIEWER, frozenset({"my-family"}))
        users.create("member-1", Role.MEMBER, frozenset({"my-family"}))
        groups = CommunityRepository(session)
        groups.create("My family", "admin-1")
        groups.create("Our village", "admin-1")
    return engine


@pytest.fixture
def client(engine):
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    app.dependency_overrides[current_principal] = lambda: ADMIN
    yield TestClient(app)
    app.dependency_overrides.clear()


def act_as(principal):
    app.dependency_overrides[current_principal] = lambda: principal


@pytest.mark.parametrize(
    ("name", "expected"),
    [("My family", "my-family"), ("  Our   Village! ", "our-village"), ("A" * 80, "a" * 48)],
)
def test_the_id_is_made_from_the_name(name, expected):
    assert slugify(name) == expected


def test_a_name_without_letters_still_gets_an_id():
    assert slugify("தமிழ்").startswith("group-")


def test_two_groups_with_one_name_get_different_ids(client):
    first = client.post("/admin/groups", json={"name": "Choir"}).json()
    second = client.post("/admin/groups", json={"name": "Choir"}).json()
    assert (first["id"], second["id"]) == ("choir", "choir-2")


def test_admin_sees_every_group(client):
    names = [g["name"] for g in client.get("/admin/groups").json()]
    assert names == ["My family", "Our village"]


def test_coordinator_sees_only_their_own_groups(client):
    act_as(COORDINATOR)
    assert [g["id"] for g in client.get("/admin/groups").json()] == ["my-family"]


def test_the_creator_joins_the_new_group_and_it_is_audited(client, engine):
    act_as(COORDINATOR)
    group = client.post("/admin/groups", json={"name": "Choir"}).json()
    with Session(engine) as session:
        assert UserRepository(session).get("coord-1").communities == {"my-family", "choir"}
        actions = [r.action for r in session.scalars(select(AuditLogRow))]
    assert actions == ["group:create"]
    assert group == {"id": "choir", "name": "Choir"}


def test_members_cannot_manage_groups(client):
    act_as(MEMBER)
    assert client.get("/admin/groups").status_code == 403
    assert client.post("/admin/groups", json={"name": "Choir"}).status_code == 403


@pytest.mark.parametrize("name", ["", "x", " ", "n" * 81])
def test_bad_names_are_refused(client, name):
    assert client.post("/admin/groups", json={"name": name}).status_code == 422


def test_coordinator_manages_consents_only_for_their_groups(client):
    act_as(COORDINATOR)
    body = {"community_id": "my-family", "rights": ["playback"]}
    created = client.post("/admin/consents", json=body)
    assert created.status_code == 201
    other = client.post("/admin/consents", json={**body, "community_id": "our-village"})
    assert other.status_code == 403
    assert client.get("/admin/consents?community_id=our-village").status_code == 403
    listed = client.get("/admin/consents?community_id=my-family").json()
    assert [c["id"] for c in listed] == [created.json()["id"]]


def test_coordinator_cannot_read_or_revoke_another_groups_consent(client, engine):
    with session_scope(engine) as session:
        ConsentRepository(session).add(consent("consent-v", community="our-village"))
    act_as(COORDINATOR)
    assert client.get("/admin/consents/consent-v").status_code == 404
    assert client.post("/admin/consents/consent-v/revoke").status_code == 404


def test_coordinator_can_revoke_their_groups_consent(client, engine):
    with session_scope(engine) as session:
        ConsentRepository(session).add(consent("consent-f", community="my-family"))
    act_as(COORDINATOR)
    assert client.post("/admin/consents/consent-f/revoke").status_code == 200


def test_a_contributor_sees_their_groups_with_active_consents_only(client, engine):
    with session_scope(engine) as session:
        repo = ConsentRepository(session)
        repo.add(consent("consent-ok", community="my-family"))
        repo.add(consent("consent-old", community="my-family", revoked=True))
        repo.add(consent("consent-other", community="our-village"))
    act_as(MEMBER)
    groups = client.get("/v1/groups/mine").json()
    assert [(g["id"], [c["id"] for c in g["consents"]]) for g in groups] == [
        ("my-family", ["consent-ok"])
    ]
