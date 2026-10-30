import time
from datetime import UTC, datetime

import boto3
import jwt
import pytest
from botocore.stub import Stubber
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.adapters.cognito import CognitoIdentityProvider
from app.api.admin import get_identity_provider
from app.api.auth import get_key_resolver, get_session_factory
from app.api.main import app
from app.db.repositories import UserRepository
from app.db.session import session_scope
from app.db.tables import AuditLogRow, Base
from app.fakes import FakeIdentityProvider
from app.models.users import Signup, UserStatus
from app.ports import IdentityProvider
from app.security.jwt import CognitoConfig
from app.security.roles import Role

CONFIG = CognitoConfig("eu-west-2", "eu-west-2_TESTPOOL", "client-1")
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class StaticKeys:
    def signing_key(self, token):
        return KEY.public_key()


def auth(sub, group):
    claims = {
        "sub": sub,
        "iss": CONFIG.issuer,
        "client_id": CONFIG.client_id,
        "token_use": "access",
        "cognito:groups": [group],
        "exp": int(time.time()) + 600,
    }
    return {"Authorization": f"Bearer {jwt.encode(claims, KEY, algorithm='RS256')}"}


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'admin.db'}")
    Base.metadata.create_all(engine)
    with session_scope(engine) as session:
        users = UserRepository(session)
        users.create("admin-1", Role.ADMIN, frozenset())
        users.create("member-1", Role.MEMBER, frozenset({"c1"}))
        users.create("reviewer-1", Role.REVIEWER, frozenset({"c1"}))
    return engine


@pytest.fixture
def idp():
    return FakeIdentityProvider()


@pytest.fixture
def client(engine, idp, monkeypatch):
    monkeypatch.setenv("HERITAGEVOICE_COGNITO_REGION", CONFIG.region)
    monkeypatch.setenv("HERITAGEVOICE_COGNITO_USER_POOL_ID", CONFIG.user_pool_id)
    monkeypatch.setenv("HERITAGEVOICE_COGNITO_APP_CLIENT_ID", CONFIG.client_id)
    monkeypatch.delenv("HERITAGEVOICE_DEV_API_TOKEN", raising=False)
    app.dependency_overrides[get_key_resolver] = StaticKeys
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    app.dependency_overrides[get_identity_provider] = lambda: idp
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def stored(engine, sub):
    with Session(engine) as session:
        return UserRepository(session).get(sub)


ADMIN = auth("admin-1", "admin")
ENDPOINTS = [
    ("post", "/admin/users", {"email": "a@example.org"}),
    ("put", "/admin/users/member-1/role", {"role": "reviewer"}),
    ("put", "/admin/users/member-1/communities", {"communities": ["c2"]}),
    ("post", "/admin/users/member-1/disable", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
def test_only_admins_may_use_admin_endpoints(client, method, path, body):
    send = getattr(client, method)
    assert send(path, json=body).status_code == 401
    assert send(path, json=body, headers=auth("member-1", "member")).status_code == 403
    assert send(path, json=body, headers=auth("reviewer-1", "reviewer")).status_code == 403


def test_a_member_cannot_make_themselves_admin(client, engine):
    response = client.put(
        "/admin/users/member-1/role", json={"role": "admin"}, headers=auth("member-1", "admin")
    )
    assert response.status_code == 403
    assert stored(engine, "member-1").role == Role.MEMBER


def test_invite_creates_the_account_membership_and_audit_entry(client, engine, idp):
    response = client.post(
        "/admin/users",
        json={"email": "new@example.org", "role": "reviewer", "communities": ["c1", "c2"]},
        headers=ADMIN,
    )
    sub = response.json()["sub"]
    assert response.status_code == 201
    assert idp.calls == [("invite", "new@example.org", "reviewer", sub)]
    user = stored(engine, sub)
    assert (user.role, user.communities) == (Role.REVIEWER, frozenset({"c1", "c2"}))
    with Session(engine) as session:
        entry = session.scalars(select(AuditLogRow)).one()
    assert (entry.actor_sub, entry.action, entry.target) == (
        "admin-1",
        "user:invite",
        f"user:{sub}",
    )
    assert len(entry.trace_id) >= 8
    assert "new@example.org" not in {entry.actor_sub, entry.action, entry.target, entry.trace_id}


@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email"},
        {"email": "a@example.org", "role": "root"},
        {"email": "a@example.org", "communities": ["../etc"]},
        {"email": "a@example.org", "surprise": True},
    ],
)
def test_invalid_invites_are_rejected_before_anything_is_created(client, idp, body):
    assert client.post("/admin/users", json=body, headers=ADMIN).status_code == 422
    assert idp.calls == []


def test_role_and_membership_changes_apply_immediately(client, engine, idp):
    headers = auth("member-1", "reviewer")
    assert client.put(
        "/admin/users/member-1/role", json={"role": "reviewer"}, headers=ADMIN
    ).json() == {"sub": "member-1", "role": "reviewer"}
    assert ("set_role", "member-1", "reviewer") in idp.calls
    assert stored(engine, "member-1").role == Role.REVIEWER
    client.put("/admin/users/member-1/communities", json={"communities": ["c9"]}, headers=ADMIN)
    assert stored(engine, "member-1").communities == {"c9"}
    assert client.post("/v1/query", json={"question": "Who?"}, headers=headers).status_code == 503


def test_admins_cannot_change_or_disable_themselves(client):
    assert (
        client.put("/admin/users/admin-1/role", json={"role": "member"}, headers=ADMIN).status_code
        == 400
    )
    assert client.post("/admin/users/admin-1/disable", headers=ADMIN).status_code == 400


def test_unknown_users_are_404_and_bad_ids_are_422(client):
    assert client.post("/admin/users/ghost/disable", headers=ADMIN).status_code == 404
    assert client.post("/admin/users/bad%20id/disable", headers=ADMIN).status_code == 422


def test_disabling_blocks_the_user_at_once_and_signs_them_out(client, engine, idp):
    member = auth("member-1", "member")
    assert client.post("/v1/query", json={"question": "Who?"}, headers=member).status_code == 503
    assert client.post("/admin/users/member-1/disable", headers=ADMIN).status_code == 200
    assert idp.calls[-1] == ("disable", "member-1")
    assert stored(engine, "member-1").status == UserStatus.DISABLED
    assert client.post("/v1/query", json={"question": "Who?"}, headers=member).status_code == 403


def test_a_failing_identity_call_still_leaves_the_user_blocked(client, engine):
    class Broken(FakeIdentityProvider):
        def disable_user(self, sub):
            raise RuntimeError("identity service down")

    app.dependency_overrides[get_identity_provider] = Broken
    response = client.post("/admin/users/member-1/disable", headers=ADMIN)
    assert response.status_code == 500
    assert stored(engine, "member-1").status == UserStatus.DISABLED


def test_the_identity_provider_is_503_when_not_configured(monkeypatch):
    monkeypatch.delenv("HERITAGEVOICE_COGNITO_USER_POOL_ID", raising=False)
    with pytest.raises(HTTPException) as error:
        get_identity_provider()
    assert error.value.status_code == 503


def test_the_fake_and_the_cognito_adapter_satisfy_the_port(idp):
    cognito = CognitoIdentityProvider("eu-west-2", "pool", client=object())
    assert isinstance(idp, IdentityProvider)
    assert isinstance(cognito, IdentityProvider)


@pytest.fixture
def cognito_stub():
    client = boto3.client(
        "cognito-idp",
        region_name="eu-west-2",
        aws_access_key_id="test-only",
        aws_secret_access_key="test-only",  # noqa: S106
    )
    with Stubber(client) as stubber:
        yield CognitoIdentityProvider("eu-west-2", "eu-west-2_TESTPOOL", client), stubber


def test_cognito_invite_sends_valid_requests(cognito_stub):
    provider, stubber = cognito_stub
    pool = {"UserPoolId": "eu-west-2_TESTPOOL"}
    stubber.add_response(
        "admin_create_user",
        {"User": {"Attributes": [{"Name": "sub", "Value": "abc-123"}]}},
        {
            **pool,
            "Username": "a@example.org",
            "UserAttributes": [
                {"Name": "email", "Value": "a@example.org"},
                {"Name": "email_verified", "Value": "true"},
            ],
            "DesiredDeliveryMediums": ["EMAIL"],
        },
    )
    stubber.add_response(
        "admin_list_groups_for_user", {"Groups": []}, {**pool, "Username": "abc-123"}
    )
    stubber.add_response(
        "admin_add_user_to_group", {}, {**pool, "Username": "abc-123", "GroupName": "reviewer"}
    )
    assert provider.invite_user("a@example.org", Role.REVIEWER) == "abc-123"
    stubber.assert_no_pending_responses()


def test_cognito_set_role_moves_the_user_between_groups(cognito_stub):
    provider, stubber = cognito_stub
    pool = {"UserPoolId": "eu-west-2_TESTPOOL", "Username": "abc-123"}
    stubber.add_response("admin_list_groups_for_user", {"Groups": [{"GroupName": "member"}]}, pool)
    stubber.add_response("admin_remove_user_from_group", {}, {**pool, "GroupName": "member"})
    stubber.add_response("admin_add_user_to_group", {}, {**pool, "GroupName": "admin"})
    provider.set_role("abc-123", Role.ADMIN)
    stubber.assert_no_pending_responses()


def test_cognito_disable_also_signs_the_user_out(cognito_stub):
    provider, stubber = cognito_stub
    pool = {"UserPoolId": "eu-west-2_TESTPOOL", "Username": "abc-123"}
    stubber.add_response("admin_disable_user", {}, pool)
    stubber.add_response("admin_user_global_sign_out", {}, pool)
    provider.disable_user("abc-123")
    stubber.assert_no_pending_responses()


# --- people who create an account themselves, waiting for approval ---------------------------

WAITING = Signup(sub="new-1", email="new@example.org", created="2026-10-30")


def test_the_waiting_list_shows_only_people_not_yet_approved(client, idp):
    idp.signups = [WAITING, Signup(sub="member-1", email="m@example.org", created="2026-10-01")]
    response = client.get("/admin/signups", headers=ADMIN)
    assert response.status_code == 200
    assert response.json() == [
        {"sub": "new-1", "email": "new@example.org", "created": "2026-10-30"}
    ]


def test_approving_makes_a_contributor_with_their_community_and_audits_it(client, engine, idp):
    idp.signups = [WAITING]
    response = client.post(
        "/admin/signups/new-1/approve", json={"communities": ["c1", "c2"]}, headers=ADMIN
    )
    assert response.status_code == 201
    assert idp.calls == [("set_role", "new-1", "member")]
    user = stored(engine, "new-1")
    assert (user.role, user.communities) == (Role.MEMBER, frozenset({"c1", "c2"}))
    with Session(engine) as session:
        entry = session.scalars(select(AuditLogRow)).one()
    assert (entry.action, entry.target) == ("signup:approve", "user:new-1")


def test_approval_never_makes_an_admin_or_reviewer(client, engine, idp):
    idp.signups = [WAITING]
    client.post(
        "/admin/signups/new-1/approve",
        json={"communities": ["c1"], "role": "admin"},
        headers=ADMIN,
    )
    assert stored(engine, "new-1") is None  # unknown field refused, nothing created
    client.post("/admin/signups/new-1/approve", json={"communities": ["c1"]}, headers=ADMIN)
    assert stored(engine, "new-1").role == Role.MEMBER


@pytest.mark.parametrize(
    "body", [{}, {"communities": []}, {"communities": ["bad id!"]}, {"communities": ["c"] * 21}]
)
def test_approval_needs_valid_communities(client, engine, idp, body):
    idp.signups = [WAITING]
    assert client.post("/admin/signups/new-1/approve", json=body, headers=ADMIN).status_code == 422
    assert stored(engine, "new-1") is None
    assert idp.calls == []


def test_only_a_real_waiting_account_can_be_approved_or_declined(client, engine, idp):
    body = {"communities": ["c1"]}
    assert client.post("/admin/signups/ghost/approve", json=body, headers=ADMIN).status_code == 404
    assert client.post("/admin/signups/ghost/decline", headers=ADMIN).status_code == 404
    idp.signups = [Signup(sub="member-1", email="m@example.org", created="2026-10-01")]
    assert (
        client.post("/admin/signups/member-1/approve", json=body, headers=ADMIN).status_code == 404
    )
    assert idp.calls == []


def test_declining_disables_the_account_and_creates_no_record(client, engine, idp):
    idp.signups = [WAITING]
    response = client.post("/admin/signups/new-1/decline", headers=ADMIN)
    assert response.status_code == 200
    assert idp.calls == [("disable", "new-1")]
    assert stored(engine, "new-1") is None


def test_a_failed_identity_call_grants_nothing(client, engine):
    class Broken(FakeIdentityProvider):
        def set_role(self, sub, role):
            raise RuntimeError("identity service down")

    broken = Broken()
    broken.signups = [WAITING]
    app.dependency_overrides[get_identity_provider] = lambda: broken
    response = client.post(
        "/admin/signups/new-1/approve", json={"communities": ["c1"]}, headers=ADMIN
    )
    assert response.status_code == 500
    assert stored(engine, "new-1") is None


@pytest.mark.parametrize("who", ["member-1", "reviewer-1"])
def test_only_admins_see_or_decide_the_waiting_list(client, idp, who):
    idp.signups = [WAITING]
    headers = auth(who, "member" if who == "member-1" else "reviewer")
    assert client.get("/admin/signups", headers=headers).status_code == 403
    body = {"communities": ["c1"]}
    assert (
        client.post("/admin/signups/new-1/approve", json=body, headers=headers).status_code == 403
    )
    assert client.post("/admin/signups/new-1/decline", headers=headers).status_code == 403


def test_an_account_with_no_record_is_denied_everywhere(client):
    stranger = auth("stranger-1", "member")
    assert client.get("/v1/me", headers=stranger).status_code == 403
    assert client.get("/v1/library", headers=stranger).status_code == 403


def user_record(email, status="CONFIRMED", verified="true", enabled=True):
    return {
        "Username": "x",
        "UserStatus": status,
        "Enabled": enabled,
        "UserCreateDate": datetime(2026, 10, 30, tzinfo=UTC),
        "Attributes": [
            {"Name": "sub", "Value": f"sub-{email}"},
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": verified},
        ],
    }


def test_cognito_lists_only_confirmed_verified_enabled_accounts(cognito_stub):
    provider, stubber = cognito_stub
    users = [
        user_record("ok@example.org"),
        user_record("unconfirmed@example.org", status="UNCONFIRMED"),
        user_record("unverified@example.org", verified="false"),
        user_record("disabled@example.org", enabled=False),
    ]
    stubber.add_response(
        "list_users", {"Users": users}, {"UserPoolId": "eu-west-2_TESTPOOL", "Limit": 60}
    )
    assert provider.list_signups() == [
        Signup(sub="sub-ok@example.org", email="ok@example.org", created="2026-10-30")
    ]


def test_cognito_listing_follows_pages_and_stops(cognito_stub):
    provider, stubber = cognito_stub
    base = {"UserPoolId": "eu-west-2_TESTPOOL", "Limit": 60}
    stubber.add_response(
        "list_users", {"Users": [user_record("a@example.org")], "PaginationToken": "t1"}, base
    )
    stubber.add_response(
        "list_users", {"Users": [user_record("b@example.org")]}, {**base, "PaginationToken": "t1"}
    )
    assert [s.email for s in provider.list_signups()] == ["a@example.org", "b@example.org"]
    stubber.assert_no_pending_responses()
