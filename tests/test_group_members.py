import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.admin import get_identity_provider
from app.api.auth import current_principal, get_session_factory
from app.api.main import app
from app.db.repositories import CommunityRepository, UserRepository
from app.db.session import session_scope
from app.db.tables import AuditLogRow, Base
from app.fakes import FakeIdentityProvider
from app.models.users import UserStatus
from app.security.roles import Role
from tests.helpers import person

ADMIN = person(Role.ADMIN, user_id="admin-1", communities=())
COORDINATOR = person(Role.REVIEWER, user_id="coord-1", communities=("my-family",))
MEMBER = person(Role.MEMBER, user_id="member-1", communities=())


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'members.db'}")
    Base.metadata.create_all(engine)
    with session_scope(engine) as session:
        users = UserRepository(session)
        users.create("coord-1", Role.REVIEWER, frozenset({"my-family"}))
        users.create("aunt-1", Role.MEMBER, frozenset())
        users.create("gone-1", Role.MEMBER, frozenset())
        users.set_status("gone-1", UserStatus.DISABLED)
        groups = CommunityRepository(session)
        groups.create("My family", "coord-1")
        groups.create("Our village", "admin-1")
    return engine


@pytest.fixture
def idp():
    provider = FakeIdentityProvider()
    provider.emails = {
        "coord-1": "coord@example.org",
        "aunt-1": "aunt@example.org",
        "gone-1": "gone@example.org",
        "new-1": "new@example.org",
    }
    return provider


@pytest.fixture
def client(engine, idp):
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    app.dependency_overrides[get_identity_provider] = lambda: idp
    app.dependency_overrides[current_principal] = lambda: COORDINATOR
    yield TestClient(app)
    app.dependency_overrides.clear()


def act_as(principal):
    app.dependency_overrides[current_principal] = lambda: principal


def add(client, email, group="my-family"):
    return client.post(f"/admin/groups/{group}/members", json={"email": email})


def members(engine, group="my-family"):
    with Session(engine) as session:
        return UserRepository(session).members_of(group)


def test_a_coordinator_adds_a_person_to_their_family_by_email(client, engine):
    response = add(client, "aunt@example.org")
    assert (response.status_code, response.json()["sub"]) == (201, "aunt-1")
    assert members(engine) == ["aunt-1", "coord-1"]


def test_the_members_are_listed_with_their_emails(client):
    add(client, "aunt@example.org")
    listed = client.get("/admin/groups/my-family/members").json()
    assert [m["email"] for m in listed] == ["aunt@example.org", "coord@example.org"]


def test_someone_without_an_account_or_not_yet_approved_cannot_be_added(client, engine):
    stranger = add(client, "nobody@example.org")
    assert (stranger.status_code, stranger.json()["detail"]["code"]) == (404, "not_signed_up")
    unapproved = add(client, "new@example.org")
    assert (unapproved.status_code, unapproved.json()["detail"]["code"]) == (404, "not_approved")
    disabled = add(client, "gone@example.org")
    assert disabled.json()["detail"]["code"] == "not_approved"
    assert members(engine) == ["coord-1"]


def test_a_coordinator_cannot_touch_a_group_they_do_not_belong_to(client, engine):
    assert add(client, "aunt@example.org", "our-village").status_code == 404
    assert client.get("/admin/groups/our-village/members").status_code == 404
    assert members(engine, "our-village") == []


def test_the_open_space_and_unknown_groups_cannot_be_managed(client):
    act_as(ADMIN)
    assert add(client, "aunt@example.org", "everyone").status_code == 404
    assert add(client, "aunt@example.org", "nope").status_code == 404


def test_an_admin_can_manage_any_group(client, engine):
    act_as(ADMIN)
    assert add(client, "aunt@example.org", "our-village").status_code == 201
    assert members(engine, "our-village") == ["aunt-1"]


def test_a_member_is_removed_from_the_group_only(client, engine):
    add(client, "aunt@example.org")
    assert client.delete("/admin/groups/my-family/members/aunt-1").status_code == 200
    assert members(engine) == ["coord-1"]
    assert client.delete("/admin/groups/my-family/members/aunt-1").status_code == 404


def test_members_cannot_manage_membership(client):
    act_as(MEMBER)
    assert add(client, "aunt@example.org").status_code == 403
    assert client.get("/admin/groups/my-family/members").status_code == 403


@pytest.mark.parametrize(
    "email", ['a"b@example.org', "no-at-sign", "a b@example.org", "a\\b@x.org"]
)
def test_odd_email_addresses_are_refused_before_the_lookup(client, email):
    assert add(client, email).status_code == 422


def test_changes_are_audited_by_account_id_not_email(client, engine):
    add(client, "aunt@example.org")
    client.delete("/admin/groups/my-family/members/aunt-1")
    with Session(engine) as session:
        entries = session.scalars(select(AuditLogRow)).all()
    assert [(e.action, e.target, e.detail) for e in entries] == [
        ("group:add_member", "group:my-family", "aunt-1"),
        ("group:remove_member", "group:my-family", "aunt-1"),
    ]
