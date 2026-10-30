"""The admin portal's keys and settings: saved encrypted, never shown again, never widened."""

import secrets

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.auth import current_principal, get_session_factory
from app.api.integrations import get_pinecone_check, get_reader, get_writer
from app.api.main import app
from app.db.repositories import ModelCatalogRepository
from app.db.session import session_scope
from app.db.tables import AuditLogRow, Base
from app.models.llm import NewModel, ProbeResult, Provider
from app.secrets import (
    NOT_CONFIGURED,
    WRITE_DENIED,
    ParameterStoreSecrets,
    SecretsConfig,
    SecretWriteError,
)
from app.security.roles import Role
from tests.helpers import person

ADMIN = person(Role.ADMIN, user_id="admin-1", communities=())


class Store:
    """An in-memory Parameter Store: the reader's client and the writer's target."""

    def __init__(self):
        self.values, self.writes = {}, []

    def get_parameter(self, Name, WithDecryption):  # noqa: N803 - boto3 parameter names
        from botocore.exceptions import ClientError  # noqa: PLC0415

        key = Name.rsplit("/", 1)[1]
        if key not in self.values:
            raise ClientError({"Error": {"Code": "ParameterNotFound", "Message": "x"}}, "Get")
        return {"Parameter": {"Value": self.values[key]}}


class FakeWriter:
    def __init__(self, store, error=None):
        self.store, self.error = store, error

    def put(self, name, value, secret):
        if self.error is not None:
            raise self.error
        self.store.writes.append((name, secret))
        self.store.values[name] = value


@pytest.fixture
def store():
    return Store()


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'integrations.db'}")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def client(engine, store):
    reader = ParameterStoreSecrets(SecretsConfig(path="/p", client=store, environ={}))
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    app.dependency_overrides[current_principal] = lambda: ADMIN
    app.dependency_overrides[get_reader] = lambda: reader
    app.dependency_overrides[get_writer] = lambda: FakeWriter(store)
    yield TestClient(app)
    app.dependency_overrides.clear()


def act_as(principal):
    app.dependency_overrides[current_principal] = lambda: principal


def items(client):
    groups = client.get("/admin/integrations").json()["groups"]
    return {i["name"]: i for g in groups for i in g["items"]}


def put(client, name, value):
    return client.put(f"/admin/integrations/{name}", json={"value": value})


@pytest.mark.parametrize("role", [Role.MEMBER, Role.REVIEWER])
def test_only_admins_see_or_change_integrations(client, role):
    act_as(person(role))
    assert client.get("/admin/integrations").status_code == 403
    assert put(client, "OPENAI_API_KEY", "abc12345").status_code == 403
    assert client.post("/admin/integrations/pinecone/test").status_code == 403


def test_the_overview_groups_the_services_and_marks_whats_missing(client):
    body = client.get("/admin/integrations").json()
    assert [g["label"] for g in body["groups"]] == [
        "Language models",
        "Pinecone (meaning-based search)",
        "LangSmith (monitoring)",
        "Neo4j (knowledge graph)",
    ]
    found = items(client)
    assert found["OPENAI_API_KEY"]["configured"] is False
    assert found["EMBEDDING_MODEL"]["default"] == "multilingual-e5-large"
    assert found["NEO4J_URI"]["planned"] is True


def test_a_saved_secret_is_stored_encrypted_and_then_only_reported_as_configured(client, store):
    key = secrets.token_hex(12)
    response = put(client, "OPENAI_API_KEY", key)
    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert response.json()["value"] is None
    assert store.writes == [("OPENAI_API_KEY", True)]
    assert items(client)["OPENAI_API_KEY"]["configured"] is True
    assert key not in client.get("/admin/integrations").text
    assert key not in response.text


def test_a_plain_setting_is_stored_as_text_and_its_value_is_shown(client, store):
    response = put(client, "PINECONE_INDEX", "heritage-prod")
    assert response.json()["value"] == "heritage-prod"
    assert store.writes == [("PINECONE_INDEX", False)]
    assert items(client)["PINECONE_INDEX"]["value"] == "heritage-prod"


def test_a_secret_never_appears_in_any_response_or_in_the_audit_log(client, engine):
    key = secrets.token_hex(12)
    responses = [
        put(client, "OPENAI_API_KEY", key),
        client.get("/admin/integrations"),
        put(client, "OPENAI_API_KEY", key + "!!"),  # invalid characters: rejected
        put(client, "POSTGRES_PASSWORD", key),  # not writable
        client.put("/admin/integrations/OPENAI_API_KEY", json={"value": key, "extra": key}),
    ]
    assert all(key not in r.text for r in responses)
    with Session(engine) as session:
        rows = session.scalars(select(AuditLogRow)).all()
    assert [(r.action, r.target, r.detail) for r in rows] == [
        ("integration:set", "integration:OPENAI_API_KEY", "secret")
    ]
    assert key not in str([(r.actor_sub, r.detail, r.target) for r in rows])


@pytest.mark.parametrize(
    "value",
    ["", "has space", "a\nb", 'quo"te', "dol$lar", "back`tick", "x" * 513, "semi;colon", "$(cmd)"],
    ids=[
        "empty",
        "space",
        "newline",
        "quote",
        "dollar",
        "backtick",
        "long",
        "semicolon",
        "subshell",
    ],
)
def test_a_value_that_could_break_a_config_file_is_refused_before_anything_is_written(
    client, store, value
):
    response = put(client, "OPENAI_API_KEY", value)
    assert (response.status_code, response.json()["detail"]["code"]) == (422, "invalid_value")
    assert store.writes == []


@pytest.mark.parametrize(
    "name",
    [
        "POSTGRES_PASSWORD",
        "HV_COOKIE_SECRET",
        "HV_COGNITO_CLIENT_SECRET",
        "HV_DOMAIN",
        "NOPE",
        "lower_api_key",
    ],
)
def test_the_portal_cannot_write_anything_outside_its_list(client, store, name):
    response = put(client, name, "abc12345")
    assert (response.status_code, response.json()["detail"]["code"]) == (404, "unknown_integration")
    assert store.writes == []


def test_a_catalogue_models_own_api_key_appears_and_can_be_written(client, engine, store):
    with session_scope(engine) as session:
        ModelCatalogRepository(session).add(
            NewModel(model_id="acme-1", provider=Provider.OPENAI, key_name="ACME_API_KEY"), "a"
        )
    assert "ACME_API_KEY" in items(client)
    assert put(client, "ACME_API_KEY", "abc12345").status_code == 200
    assert store.writes == [("ACME_API_KEY", True)]


def test_a_catalogue_key_not_ending_in_api_key_cannot_be_written_from_the_portal(
    client, engine, store
):
    with session_scope(engine) as session:
        ModelCatalogRepository(session).add(
            NewModel(model_id="acme-2", provider=Provider.OPENAI, key_name="ACME_SECRET"), "a"
        )
    assert "ACME_SECRET" not in items(client)
    assert put(client, "ACME_SECRET", "abc12345").status_code == 404


@pytest.mark.parametrize("code", [WRITE_DENIED, NOT_CONFIGURED, "write_failed"])
def test_a_failed_save_is_a_safe_503_with_a_short_code(client, store, code):
    app.dependency_overrides[get_writer] = lambda: FakeWriter(store, SecretWriteError(code))
    response = put(client, "OPENAI_API_KEY", "abc12345")
    assert (response.status_code, response.json()["detail"]) == (503, {"code": code})
    assert "abc12345" not in response.text


def test_a_failed_save_is_not_audited_as_if_it_happened(client, engine, store):
    app.dependency_overrides[get_writer] = lambda: FakeWriter(store, SecretWriteError(WRITE_DENIED))
    put(client, "OPENAI_API_KEY", "abc12345")
    with Session(engine) as session:
        assert session.scalars(select(AuditLogRow)).all() == []


def test_the_new_value_is_visible_at_once_not_after_the_cache_expires(client):
    assert items(client)["PINECONE_INDEX"]["configured"] is False  # caches the miss
    put(client, "PINECONE_INDEX", "heritage-prod")
    assert items(client)["PINECONE_INDEX"]["value"] == "heritage-prod"


class Probe:
    def __init__(self, result):
        self.result, self.seen = result, []

    def check(self, api_key, index, dimension):
        self.seen.append((api_key, index, dimension))
        return self.result


def test_the_pinecone_test_uses_the_saved_key_index_and_dimension(client):
    put(client, "PINECONE_API_KEY", "pc-key-123")
    put(client, "PINECONE_INDEX", "heritage-prod")
    put(client, "EMBEDDING_DIMENSION", "768")
    probe = Probe(ProbeResult(ok=True))
    app.dependency_overrides[get_pinecone_check] = lambda: probe
    assert client.post("/admin/integrations/pinecone/test").json() == {"ok": True, "code": None}
    key, index, dimension = probe.seen[0]
    assert (key.get_secret_value(), index, dimension) == ("pc-key-123", "heritage-prod", 768)


def test_the_pinecone_test_falls_back_to_the_default_dimension_and_never_returns_the_key(client):
    put(client, "PINECONE_API_KEY", "pc-key-123")
    probe = Probe(ProbeResult(ok=False, code="unknown_index"))
    app.dependency_overrides[get_pinecone_check] = lambda: probe
    response = client.post("/admin/integrations/pinecone/test")
    assert response.json() == {"ok": False, "code": "unknown_index"}
    assert "pc-key-123" not in response.text
    assert probe.seen[0][2] == 1024
