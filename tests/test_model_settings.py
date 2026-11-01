import secrets

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.adapters.model_tester import ProviderModelTester, _code_for
from app.api.auth import current_principal, get_session_factory
from app.api.main import app
from app.api.model_settings import get_model_tester, get_secrets
from app.config import Settings
from app.db.repositories import ModelCatalogRepository, ModelSettingRepository
from app.db.session import session_scope
from app.db.tables import AuditLogRow, Base
from app.model_registry import ModelRegistry, default_setting
from app.models.llm import (
    DEFAULT_KEY_NAME,
    SEED_MODELS,
    ModelParams,
    ModelRole,
    ModelStatus,
    NewModel,
    ProbeResult,
    Provider,
)
from app.ports import ModelTester
from app.security.roles import Role
from tests.helpers import person

ADMIN = person(Role.ADMIN, user_id="admin-1", communities=())
PARAMS = {"provider": "anthropic", "model": "claude-haiku-5-5", "temperature": 0.2}
CATALOG_SIZE = len(SEED_MODELS[Provider.ANTHROPIC])


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'models.db'}")
    Base.metadata.create_all(engine)
    with session_scope(engine) as session:
        catalog = ModelCatalogRepository(session)
        for model in SEED_MODELS[Provider.ANTHROPIC]:
            catalog.add(NewModel(model_id=model, provider=Provider.ANTHROPIC), "system")
    return engine


def sessions(engine):
    return lambda: session_scope(engine)


def save(engine, **overrides):
    params = ModelParams(**{**PARAMS, **overrides})
    with session_scope(engine) as session:
        ModelSettingRepository(session).upsert(ModelRole.TRANSLATION, params, "admin-1")


def set_status(engine, model_id, status):
    with session_scope(engine) as session:
        ModelCatalogRepository(session).set_status(model_id, status)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeSecrets:
    def __init__(self, **values):
        self.values = values

    def get(self, name):
        value = self.values.get(name)
        return SecretStr(value) if value else None

    def is_configured(self, name):
        return self.get(name) is not None


def registry_for(engine, **kwargs):
    return ModelRegistry(sessions(engine), Settings(_env_file=None), **kwargs)


# --- registry: which setting is in force ---------------------------------------------------


def test_the_environment_default_applies_until_an_admin_saves_a_setting(engine):
    env = Settings(
        _env_file=None, llm_model="claude-sonnet-5-5", llm_timeout_s=45, llm_max_retries=1
    )
    setting = ModelRegistry(sessions(engine), env).get(ModelRole.TRANSLATION)
    assert (setting.model, setting.timeout_s, setting.max_retries) == ("claude-sonnet-5-5", 45, 1)
    assert setting == default_setting(ModelRole.TRANSLATION, env)
    assert setting.fallbacks == ()


def test_a_saved_setting_wins_and_is_picked_up_after_the_cache_expires(engine):
    clock = Clock()
    registry = registry_for(engine, ttl_s=60, clock=clock)
    assert registry.get(ModelRole.TRANSLATION).model == "claude-sonnet-5-5"
    save(engine, model="claude-haiku-5-5")
    assert registry.get(ModelRole.TRANSLATION).model == "claude-sonnet-5-5"  # still cached
    clock.now = 61
    assert registry.get(ModelRole.TRANSLATION).model == "claude-haiku-5-5"


def test_invalidate_applies_a_change_at_once(engine):
    registry = registry_for(engine, ttl_s=3600)
    registry.get(ModelRole.TRANSLATION)
    save(engine, model="claude-opus-5-5")
    registry.invalidate()
    assert registry.get(ModelRole.TRANSLATION).model == "claude-opus-5-5"


def test_an_unreadable_database_keeps_the_last_known_setting(engine):
    clock = Clock()
    calls = {"broken": False}

    def factory():
        if calls["broken"]:
            raise OperationalError("select", {}, Exception("db down"))
        return session_scope(engine)

    save(engine, model="claude-opus-5-5")
    registry = ModelRegistry(factory, Settings(_env_file=None), ttl_s=10, clock=clock)
    assert registry.get(ModelRole.TRANSLATION).model == "claude-opus-5-5"
    assert [link.setting.model for link in registry.chain(ModelRole.TRANSLATION)] == [
        "claude-opus-5-5"
    ]
    calls["broken"], clock.now = True, 11
    assert registry.get(ModelRole.TRANSLATION).model == "claude-opus-5-5"
    assert len(registry.chain(ModelRole.TRANSLATION)) == 1  # last known catalogue


def test_an_unreadable_database_with_nothing_cached_falls_back_to_the_default():
    def factory():
        raise OperationalError("select", {}, Exception("db down"))

    registry = ModelRegistry(factory, Settings(_env_file=None))
    assert registry.get(ModelRole.TRANSLATION).model == "claude-sonnet-5-5"
    # the primary still works from trusted configuration, with the default key
    (link,) = registry.chain(ModelRole.TRANSLATION)
    assert (link.setting.model, link.key_name) == ("claude-sonnet-5-5", DEFAULT_KEY_NAME)


# --- registry: the chain of models to try --------------------------------------------------


def chain_models(registry):
    return [link.setting.model for link in registry.chain(ModelRole.TRANSLATION)]


def test_the_chain_is_the_primary_then_the_fallbacks_in_order(engine):
    save(engine, model="claude-sonnet-5-5", fallbacks=("claude-haiku-5-5", "claude-opus-5-5"))
    registry = registry_for(engine)
    assert chain_models(registry) == ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"]
    first = registry.chain(ModelRole.TRANSLATION)[1]
    assert first.setting.fallbacks == ()  # each link is one model
    assert first.setting.temperature == 0.2  # and shares the role's limits


def test_a_disabled_model_is_skipped_but_a_deprecated_one_still_serves(engine):
    save(engine, model="claude-sonnet-5-5", fallbacks=("claude-haiku-5-5", "claude-opus-5-5"))
    set_status(engine, "claude-sonnet-5-5", ModelStatus.DISABLED)
    set_status(engine, "claude-haiku-5-5", ModelStatus.DEPRECATED)
    assert chain_models(registry_for(engine)) == ["claude-haiku-5-5", "claude-opus-5-5"]


def test_a_fallback_missing_from_the_catalogue_is_skipped(engine):
    save(engine, model="claude-sonnet-5-5", fallbacks=("not-in-the-catalogue",))
    assert chain_models(registry_for(engine)) == ["claude-sonnet-5-5"]


def test_each_link_carries_the_name_of_its_own_key(engine):
    with session_scope(engine) as session:
        ModelCatalogRepository(session).add(
            NewModel(model_id="other-model", provider=Provider.ANTHROPIC, key_name="OTHER_KEY"),
            "admin-1",
        )
    save(engine, model="claude-sonnet-5-5", fallbacks=("other-model",))
    links = registry_for(engine).chain(ModelRole.TRANSLATION)
    assert [link.key_name for link in links] == [DEFAULT_KEY_NAME, "OTHER_KEY"]


def test_changes_to_the_catalogue_apply_after_the_cache_expires(engine):
    clock = Clock()
    registry = registry_for(engine, ttl_s=60, clock=clock)
    save(engine, model="claude-sonnet-5-5", fallbacks=("claude-haiku-5-5",))
    assert chain_models(registry) == ["claude-sonnet-5-5", "claude-haiku-5-5"]
    set_status(engine, "claude-haiku-5-5", ModelStatus.DISABLED)
    assert len(chain_models(registry)) == 2  # still cached
    clock.now = 61
    assert chain_models(registry) == ["claude-sonnet-5-5"]


def test_the_params_reject_a_repeated_model_and_too_many_fallbacks():
    with pytest.raises(ValueError, match="only once"):
        ModelParams(**PARAMS, fallbacks=("claude-haiku-5-5",))
    with pytest.raises(ValueError, match="only once"):
        ModelParams(**PARAMS, fallbacks=("a", "a"))
    with pytest.raises(ValueError, match="at most 3"):
        ModelParams(**PARAMS, fallbacks=("a", "b", "c", "d"))


# --- the admin API -------------------------------------------------------------------------


@pytest.fixture
def api_key():
    return secrets.token_hex(12)


@pytest.fixture
def fake_secrets(api_key):
    return FakeSecrets(**{DEFAULT_KEY_NAME: api_key})


@pytest.fixture
def client(engine, fake_secrets):
    app.dependency_overrides[get_session_factory] = lambda: sessions(engine)
    app.dependency_overrides[current_principal] = lambda: ADMIN
    app.dependency_overrides[get_secrets] = lambda: fake_secrets
    yield TestClient(app)
    app.dependency_overrides.clear()


def act_as(principal):
    app.dependency_overrides[current_principal] = lambda: principal


NEW = {"model_id": "claude-new-1", "provider": "anthropic", "key_name": "NEW_KEY"}


@pytest.mark.parametrize("role", [Role.MEMBER, Role.REVIEWER])
def test_only_admins_manage_model_settings(client, role):
    act_as(person(role))
    assert client.get("/admin/models").status_code == 403
    assert client.post("/admin/models/catalog", json=NEW).status_code == 403
    assert (
        client.put(
            "/admin/models/catalog/claude-haiku-5-5", json={"status": "disabled"}
        ).status_code
        == 403
    )
    assert client.put("/admin/models/translation", json=PARAMS).status_code == 403
    assert client.delete("/admin/models/translation").status_code == 403
    assert client.post("/admin/models/translation/test", json=PARAMS).status_code == 403


def test_the_overview_shows_the_catalogue_with_key_status_and_the_role_defaults(client):
    body = client.get("/admin/models").json()
    assert len(body["catalog"]) == CATALOG_SIZE
    first = body["catalog"][0]
    assert (first["status"], first["key_name"], first["key_configured"]) == (
        "active",
        DEFAULT_KEY_NAME,
        True,
    )
    assert [r["role"] for r in body["roles"]] == [
        "translation",
        "supervisor",
        "verifier",
        "answer",
        "graph",
    ]
    for row in body["roles"]:
        assert (row["source"], row["model"], row["fallbacks"]) == (
            "default",
            "claude-sonnet-5-5",
            [],
        )


def test_a_missing_key_is_reported_without_revealing_anything(client, fake_secrets):
    fake_secrets.values.clear()
    catalog = client.get("/admin/models").json()["catalog"]
    assert all(entry["key_configured"] is False for entry in catalog)


def test_adding_a_model_is_stored_audited_and_listed(client, engine):
    response = client.post("/admin/models/catalog", json=NEW)
    assert response.status_code == 201
    assert response.json() == {
        **NEW,
        "status": "active",
        "key_configured": False,
        "input_price": None,
        "output_price": None,
    }
    assert len(client.get("/admin/models").json()["catalog"]) == CATALOG_SIZE + 1
    with Session(engine) as session:
        entry = session.scalars(select(AuditLogRow)).one()
    assert (entry.action, entry.target, entry.detail) == (
        "model:add",
        "model:claude-new-1",
        "anthropic/claude-new-1 key=NEW_KEY",
    )


def test_adding_a_model_twice_is_a_conflict(client):
    assert client.post("/admin/models/catalog", json=NEW).status_code == 201
    response = client.post("/admin/models/catalog", json=NEW)
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "model_exists")


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider": "mistral"},
        {"model_id": ""},
        {"model_id": "has space"},
        {"key_name": "lower_case"},
        {"key_name": "../etc/passwd"},
        {"api_key": "sk-anything"},
    ],
    ids=["provider", "empty", "space", "lower", "path", "value"],
)
def test_a_bad_catalogue_entry_is_rejected(client, engine, overrides):
    assert client.post("/admin/models/catalog", json={**NEW, **overrides}).status_code == 422
    with Session(engine) as session:
        assert len(ModelCatalogRepository(session).list_all()) == CATALOG_SIZE


def test_a_models_status_can_change_and_an_unknown_model_is_404(client):
    response = client.put("/admin/models/catalog/claude-haiku-5-5", json={"status": "deprecated"})
    assert response.json()["status"] == "deprecated"
    missing = client.put("/admin/models/catalog/nope", json={"status": "disabled"})
    assert (missing.status_code, missing.json()["detail"]["code"]) == (404, "unknown_model")
    assert (
        client.put("/admin/models/catalog/claude-haiku-5-5", json={"status": "x"}).status_code
        == 422
    )


def test_saving_a_chain_is_stored_audited_and_shown(client, engine):
    body = {**PARAMS, "fallbacks": ["claude-sonnet-5-5", "claude-opus-5-5"]}
    response = client.put("/admin/models/translation", json=body)
    assert response.json()["model"] == "claude-haiku-5-5"
    assert response.json()["fallbacks"] == ["claude-sonnet-5-5", "claude-opus-5-5"]
    assert response.json()["source"] == "database"
    assert client.get("/admin/models").json()["roles"][0]["fallbacks"][0] == "claude-sonnet-5-5"
    with Session(engine) as session:
        entry = session.scalars(select(AuditLogRow)).one()
        stored = ModelSettingRepository(session).get(ModelRole.TRANSLATION)
    assert (entry.actor_sub, entry.action, entry.target, entry.detail) == (
        "admin-1",
        "model:update",
        "model:translation",
        "anthropic/claude-haiku-5-5 > claude-sonnet-5-5 > claude-opus-5-5",
    )
    assert (stored.model, stored.fallbacks) == (
        "claude-haiku-5-5",
        ("claude-sonnet-5-5", "claude-opus-5-5"),
    )


def test_a_model_that_is_not_active_in_the_catalogue_cannot_be_chosen(client, engine):
    set_status(engine, "claude-opus-5-5", ModelStatus.DISABLED)
    set_status(engine, "claude-sonnet-5-5", ModelStatus.DEPRECATED)
    for bad in ({"model": "gpt-9000"}, {"fallbacks": ["claude-opus-5-5"]}, {"fallbacks": ["nope"]}):
        response = client.put("/admin/models/translation", json={**PARAMS, **bad})
        assert (response.status_code, response.json()["detail"]["code"]) == (
            422,
            "model_not_available",
        )
    response = client.put(
        "/admin/models/translation", json={**PARAMS, "fallbacks": ["claude-sonnet-5-5"]}
    )
    assert response.status_code == 422  # deprecated models keep serving but cannot be newly chosen
    with Session(engine) as session:
        assert ModelSettingRepository(session).get(ModelRole.TRANSLATION) is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"model": ""},
        {"provider": "mistral"},
        {"temperature": 1.5},
        {"timeout_s": 1},
        {"timeout_s": 1000},
        {"max_retries": 9},
        {"api_key": "sk-anything"},
        {"fallbacks": ["claude-haiku-5-5"]},
        {"fallbacks": ["claude-opus-5-5", "claude-opus-5-5"]},
        {"fallbacks": ["a", "b", "c", "d"]},
    ],
    ids=[
        "empty",
        "provider",
        "hot",
        "fast",
        "slow",
        "retries",
        "key",
        "repeats-primary",
        "repeats-fallback",
        "too-many",
    ],
)
def test_invalid_settings_are_rejected_and_an_api_key_can_never_be_submitted(
    client, engine, overrides
):
    assert client.put("/admin/models/translation", json={**PARAMS, **overrides}).status_code == 422
    with Session(engine) as session:
        assert ModelSettingRepository(session).get(ModelRole.TRANSLATION) is None


def test_an_unknown_role_is_422(client):
    assert client.put("/admin/models/nonsense", json=PARAMS).status_code == 422


@pytest.mark.parametrize("role", ["supervisor", "verifier", "answer"])
def test_each_agent_has_its_own_model_setting(client, role):
    saved = client.put(f"/admin/models/{role}", json={**PARAMS, "fallbacks": ["claude-opus-5-5"]})
    assert saved.status_code == 200
    roles = {r["role"]: r for r in client.get("/admin/models").json()["roles"]}
    assert roles[role]["source"] == "database"
    assert roles[role]["fallbacks"] == ["claude-opus-5-5"]
    assert roles["translation"]["source"] == "default"


def test_resetting_returns_to_the_environment_default(client, engine):
    client.put("/admin/models/translation", json=PARAMS)
    response = client.delete("/admin/models/translation")
    assert (response.json()["source"], response.json()["model"]) == ("default", "claude-sonnet-5-5")
    assert response.json()["fallbacks"] == []
    with Session(engine) as session:
        assert ModelSettingRepository(session).list_all() == []
        actions = [e.action for e in session.scalars(select(AuditLogRow))]
    assert actions == ["model:update", "model:reset"]


class FakeTester:
    def __init__(self, result):
        self.result, self.seen = result, []

    def check(self, params, api_key):
        self.seen.append((params, api_key))
        return self.result


def test_the_test_button_uses_the_models_own_key_and_saves_nothing(client, engine, api_key):
    tester = FakeTester(ProbeResult(ok=False, code="bad_key"))
    app.dependency_overrides[get_model_tester] = lambda: tester
    body = client.post("/admin/models/translation/test", json=PARAMS).json()
    assert body == {"ok": False, "code": "bad_key"}
    params, key = tester.seen[0]
    assert (params.model, key.get_secret_value()) == ("claude-haiku-5-5", api_key)
    with Session(engine) as session:
        assert ModelSettingRepository(session).list_all() == []
    app.dependency_overrides[get_model_tester] = lambda: FakeTester(ProbeResult(ok=True))
    assert client.post("/admin/models/translation/test", json=PARAMS).json() == {
        "ok": True,
        "code": None,
    }


def test_testing_a_model_outside_the_catalogue_says_so(client):
    app.dependency_overrides[get_model_tester] = lambda: FakeTester(ProbeResult(ok=True))
    body = client.post("/admin/models/translation/test", json={**PARAMS, "model": "nope"}).json()
    assert body == {"ok": False, "code": "unknown_model"}


def test_the_api_key_never_appears_in_any_response(client, api_key):
    app.dependency_overrides[get_model_tester] = lambda: FakeTester(ProbeResult(ok=True))
    responses = [
        client.get("/admin/models"),
        client.post("/admin/models/catalog", json=NEW),
        client.put("/admin/models/catalog/claude-new-1", json={"status": "disabled"}),
        client.put("/admin/models/translation", json=PARAMS),
        client.post("/admin/models/translation/test", json=PARAMS),
        client.delete("/admin/models/translation"),
        client.put("/admin/models/translation", json={**PARAMS, "api_key": api_key}),
        client.post("/admin/models/catalog", json={**NEW, "api_key": api_key}),
    ]
    assert all(api_key not in response.text for response in responses)


def test_the_tester_without_a_key_does_not_call_the_provider():
    tester = ProviderModelTester()
    result = tester.check(ModelParams(**PARAMS), None)
    assert (result.ok, result.code) == (False, "no_key")
    assert isinstance(tester, ModelTester)


def test_provider_errors_map_to_short_codes():
    response = httpx.Response(401, request=httpx.Request("POST", "http://x"))
    auth = anthropic.AuthenticationError("secret detail", response=response, body=None)
    assert _code_for(auth) == "bad_key"
    assert _code_for(RuntimeError("anything")) == "provider_error"


def test_a_refused_request_and_a_timeout_get_their_own_codes():
    request = httpx.Request("POST", "http://x")
    bad = anthropic.BadRequestError(
        "secret detail", response=httpx.Response(400, request=request), body=None
    )
    assert _code_for(bad) == "bad_request"
    assert _code_for(anthropic.APITimeoutError(request=request)) == "timeout"


def test_me_tells_the_ui_who_is_signed_in(client):
    assert client.get("/v1/me").json() == {"user_id": "admin-1", "role": "admin", "communities": []}
    act_as(person(Role.REVIEWER, user_id="r", communities=("c2", "c1")))
    assert client.get("/v1/me").json()["communities"] == ["c1", "c2"]


def test_me_needs_authentication():
    app.dependency_overrides.clear()
    assert TestClient(app).get("/v1/me").status_code in {401, 503}


# --- OpenAI as a second provider ------------------------------------------------------------


def test_an_openai_model_defaults_to_its_own_key_name(client):
    response = client.post(
        "/admin/models/catalog", json={"model_id": "gpt-example-1", "provider": "openai"}
    )
    assert response.status_code == 201
    assert response.json()["key_name"] == "OPENAI_API_KEY"
    assert response.json()["provider"] == "openai"


def test_an_anthropic_model_still_defaults_to_the_existing_key_name(client):
    response = client.post(
        "/admin/models/catalog", json={"model_id": "claude-example-1", "provider": "anthropic"}
    )
    assert response.json()["key_name"] == DEFAULT_KEY_NAME


def test_a_chain_can_fail_over_from_one_provider_to_another(engine):
    with session_scope(engine) as session:
        ModelCatalogRepository(session).add(
            NewModel(model_id="gpt-example-1", provider=Provider.OPENAI), "admin-1"
        )
    save(engine, model="claude-sonnet-5-5", fallbacks=("gpt-example-1",))
    links = registry_for(engine).chain(ModelRole.TRANSLATION)
    assert [(link.setting.provider, link.key_name) for link in links] == [
        (Provider.ANTHROPIC, DEFAULT_KEY_NAME),
        (Provider.OPENAI, "OPENAI_API_KEY"),
    ]
