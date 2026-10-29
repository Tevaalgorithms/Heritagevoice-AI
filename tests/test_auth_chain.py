import time
from typing import Annotated

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.api.auth import current_principal, get_key_resolver, get_session_factory
from app.api.main import app as main_app
from app.db.repositories import UserRepository
from app.db.session import session_scope
from app.db.tables import Base
from app.models.users import UserStatus
from app.security.jwt import CognitoConfig
from app.security.permissions import Principal, Resource, authorize
from app.security.roles import Action, Role

CONFIG = CognitoConfig("eu-west-2", "eu-west-2_TESTPOOL", "client-1")
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class StaticKeys:
    def signing_key(self, token):
        return KEY.public_key()


def token_for(sub, groups, **overrides):
    claims = {
        "sub": sub,
        "iss": CONFIG.issuer,
        "client_id": CONFIG.client_id,
        "token_use": "access",
        "cognito:groups": groups,
        "exp": int(time.time()) + 600,
        **overrides,
    }
    return jwt.encode(claims, KEY, algorithm="RS256")


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def api(engine, monkeypatch):
    monkeypatch.setenv("HERITAGEVOICE_COGNITO_REGION", CONFIG.region)
    monkeypatch.setenv("HERITAGEVOICE_COGNITO_USER_POOL_ID", CONFIG.user_pool_id)
    monkeypatch.setenv("HERITAGEVOICE_COGNITO_APP_CLIENT_ID", CONFIG.client_id)
    monkeypatch.delenv("HERITAGEVOICE_DEV_API_TOKEN", raising=False)
    app = FastAPI()

    @app.get("/me")
    def me(principal: Annotated[Principal, Depends(current_principal)]):
        return {"role": principal.role, "communities": sorted(principal.communities)}

    @app.post("/approve/{community}/{owner}")
    def approve(
        community: str, owner: str, principal: Annotated[Principal, Depends(current_principal)]
    ):
        decision = authorize(principal, Action.REVIEW_APPROVE, Resource(community, owner))
        if not decision.allowed:
            raise HTTPException(status_code=403, detail=decision.reason)
        return {"approved": True}

    app.dependency_overrides[get_key_resolver] = StaticKeys
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    return TestClient(app)


def add_user(engine, sub, role, communities=("c1",)):
    with session_scope(engine) as session:
        UserRepository(session).create(sub, role, frozenset(communities))


def test_a_valid_token_for_an_active_user_builds_the_principal(api, engine):
    add_user(engine, "u1", Role.REVIEWER, ("c1", "c2"))
    response = api.get("/me", headers=bearer(token_for("u1", ["reviewer"])))
    assert response.json() == {"role": "reviewer", "communities": ["c1", "c2"]}


def test_a_forged_reviewer_claim_cannot_raise_a_members_role(api, engine):
    add_user(engine, "u1", Role.MEMBER)
    headers = bearer(token_for("u1", ["reviewer", "admin"]))
    assert api.get("/me", headers=headers).json()["role"] == "member"
    assert api.post("/approve/c1/other", headers=headers).status_code == 403


def test_an_outdated_token_cannot_keep_a_demoted_role(api, engine):
    add_user(engine, "u1", Role.MEMBER)
    assert api.get("/me", headers=bearer(token_for("u1", ["admin"]))).json()["role"] == "member"


def test_role_claims_in_headers_or_body_are_ignored(api, engine):
    add_user(engine, "u1", Role.MEMBER)
    headers = {**bearer(token_for("u1", ["member"])), "X-Role": "admin", "X-User-Id": "root"}
    assert api.get("/me?role=admin", headers=headers).json()["role"] == "member"


def test_cross_community_approval_is_denied_even_for_a_reviewer(api, engine):
    add_user(engine, "u1", Role.REVIEWER, ("c1",))
    headers = bearer(token_for("u1", ["reviewer"]))
    assert api.post("/approve/c1/someone", headers=headers).status_code == 200
    assert api.post("/approve/c2/someone", headers=headers).status_code == 403


def test_a_reviewer_cannot_approve_their_own_upload(api, engine):
    add_user(engine, "u1", Role.REVIEWER)
    response = api.post("/approve/c1/u1", headers=bearer(token_for("u1", ["reviewer"])))
    assert response.status_code == 403
    assert response.json()["detail"] == "cannot_approve_own_upload"


@pytest.mark.parametrize("status", [UserStatus.DISABLED])
def test_a_disabled_user_is_denied_with_a_valid_token(api, engine, status):
    add_user(engine, "u1", Role.MEMBER)
    with session_scope(engine) as session:
        UserRepository(session).set_status("u1", status)
    assert api.get("/me", headers=bearer(token_for("u1", ["member"]))).status_code == 403


def test_an_unknown_user_is_denied(api):
    assert api.get("/me", headers=bearer(token_for("ghost", ["member"]))).status_code == 403


def test_a_token_with_no_known_group_is_denied(api, engine):
    add_user(engine, "u1", Role.ADMIN)
    assert api.get("/me", headers=bearer(token_for("u1", ["guests"]))).status_code == 403


def test_membership_changes_apply_on_the_next_request(api, engine):
    add_user(engine, "u1", Role.REVIEWER, ("c1",))
    headers = bearer(token_for("u1", ["reviewer"]))
    assert api.post("/approve/c2/x", headers=headers).status_code == 403
    with session_scope(engine) as session:
        UserRepository(session).set_communities("u1", frozenset({"c1", "c2"}))
    assert api.post("/approve/c2/x", headers=headers).status_code == 200


@pytest.mark.parametrize(
    "overrides",
    [{"exp": 1}, {"token_use": "id"}, {"client_id": "other"}, {"iss": "https://evil.example"}],
    ids=["expired", "id-token", "wrong-client", "wrong-issuer"],
)
def test_invalid_tokens_are_401_before_any_database_lookup(api, engine, overrides):
    add_user(engine, "u1", Role.MEMBER)
    assert (
        api.get("/me", headers=bearer(token_for("u1", ["member"], **overrides))).status_code == 401
    )


def test_missing_credentials_are_401(api):
    assert api.get("/me").status_code == 401


def test_the_dev_token_works_only_in_the_local_environment(monkeypatch):
    client = TestClient(main_app)
    monkeypatch.setenv("HERITAGEVOICE_DEV_API_TOKEN", "local-only-test-value")
    monkeypatch.delenv("HERITAGEVOICE_COGNITO_REGION", raising=False)
    good = bearer("local-only-test-value")
    assert client.post("/query", json={"question": "Who?"}, headers=good).status_code == 503
    monkeypatch.setenv("HERITAGEVOICE_ENVIRONMENT", "production")
    assert client.post("/query", json={"question": "Who?"}, headers=good).status_code == 503
    assert client.post("/query", json={"question": "Who?"}).status_code == 503


def test_in_production_a_dev_token_is_not_a_credential(monkeypatch, engine):
    monkeypatch.setenv("HERITAGEVOICE_ENVIRONMENT", "production")
    monkeypatch.setenv("HERITAGEVOICE_DEV_API_TOKEN", "local-only-test-value")
    monkeypatch.setenv("HERITAGEVOICE_COGNITO_REGION", CONFIG.region)
    monkeypatch.setenv("HERITAGEVOICE_COGNITO_USER_POOL_ID", CONFIG.user_pool_id)
    monkeypatch.setenv("HERITAGEVOICE_COGNITO_APP_CLIENT_ID", CONFIG.client_id)
    main_app.dependency_overrides[get_key_resolver] = StaticKeys
    try:
        response = TestClient(main_app).post(
            "/query", json={"question": "Who?"}, headers=bearer("local-only-test-value")
        )
    finally:
        main_app.dependency_overrides.clear()
    assert response.status_code == 401
