import secrets

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.adapters.llm_translator import ConfiguredTranslator, TranslatedSegment, TranslationBatch
from app.adapters.model_tester import AnthropicModelTester, _code_for
from app.api.auth import current_principal, get_session_factory
from app.api.main import app
from app.api.model_settings import get_model_tester
from app.config import Settings
from app.db.repositories import ModelSettingRepository
from app.db.session import session_scope
from app.db.tables import AuditLogRow, Base
from app.model_registry import ModelRegistry, default_setting
from app.models.llm import ALLOWED_MODELS, ModelParams, ModelRole, ProbeResult, Provider
from app.models.transcript import Segment
from app.ports import ModelTester
from app.security.roles import Role
from tests.helpers import person

ADMIN = person(Role.ADMIN, user_id="admin-1", communities=())
PARAMS = {"provider": "anthropic", "model": "claude-haiku-5-5", "temperature": 0.2}
SEGMENTS = [Segment(segment_id="s1", start_s=0.0, end_s=0.5, text="x")]


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'models.db'}")
    Base.metadata.create_all(engine)
    return engine


def sessions(engine):
    return lambda: session_scope(engine)


def save(engine, **overrides):
    params = ModelParams(**{**PARAMS, **overrides})
    with session_scope(engine) as session:
        ModelSettingRepository(session).upsert(ModelRole.TRANSLATION, params, "admin-1")


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_the_environment_default_applies_until_an_admin_saves_a_setting(engine):
    env = Settings(
        _env_file=None, llm_model="claude-sonnet-5-5", llm_timeout_s=45, llm_max_retries=1
    )
    registry = ModelRegistry(sessions(engine), env)
    setting = registry.get(ModelRole.TRANSLATION)
    assert (setting.model, setting.timeout_s, setting.max_retries) == ("claude-sonnet-5-5", 45, 1)
    assert setting == default_setting(ModelRole.TRANSLATION, env)


def test_a_saved_setting_wins_and_is_picked_up_after_the_cache_expires(engine):
    clock = Clock()
    registry = ModelRegistry(sessions(engine), Settings(_env_file=None), ttl_s=60, clock=clock)
    assert registry.get(ModelRole.TRANSLATION).model == "claude-sonnet-5-5"
    save(engine, model="claude-haiku-5-5")
    assert registry.get(ModelRole.TRANSLATION).model == "claude-sonnet-5-5"  # still cached
    clock.now = 61
    assert registry.get(ModelRole.TRANSLATION).model == "claude-haiku-5-5"


def test_invalidate_applies_a_change_at_once(engine):
    registry = ModelRegistry(sessions(engine), Settings(_env_file=None), ttl_s=3600)
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
    calls["broken"], clock.now = True, 11
    assert registry.get(ModelRole.TRANSLATION).model == "claude-opus-5-5"


def test_an_unreadable_database_with_nothing_cached_falls_back_to_the_default():
    def factory():
        raise OperationalError("select", {}, Exception("db down"))

    registry = ModelRegistry(factory, Settings(_env_file=None))
    assert registry.get(ModelRole.TRANSLATION).model == "claude-sonnet-5-5"


def test_the_translator_follows_the_setting_in_force(engine):
    built = []

    class FakeChain:
        def __init__(self, name):
            self.name = name

        def invoke(self, inputs):
            return TranslationBatch(segments=[TranslatedSegment(segment_id="s1", text=self.name)])

    def factory(setting, key):
        built.append((setting.model, key.get_secret_value()))
        return FakeChain(setting.model)

    registry = ModelRegistry(sessions(engine), Settings(_env_file=None), ttl_s=0)
    key = secrets.token_hex(4)
    translator = ConfiguredTranslator(
        registry, Settings(_env_file=None, llm_api_key=key).llm_api_key, factory
    )
    assert translator.translate(SEGMENTS, "en")[0].text == "claude-sonnet-5-5"
    translator.translate(SEGMENTS, "en")
    save(engine, model="claude-haiku-5-5")
    assert translator.translate(SEGMENTS, "en")[0].text == "claude-haiku-5-5"
    assert built == [
        ("claude-sonnet-5-5", key),
        ("claude-haiku-5-5", key),
    ]  # built once per setting


@pytest.fixture
def api_key():
    return secrets.token_hex(12)


@pytest.fixture
def client(engine, monkeypatch, api_key):
    monkeypatch.setenv("HERITAGEVOICE_LLM_API_KEY", api_key)
    app.dependency_overrides[get_session_factory] = lambda: sessions(engine)
    app.dependency_overrides[current_principal] = lambda: ADMIN
    yield TestClient(app)
    app.dependency_overrides.clear()


def act_as(principal):
    app.dependency_overrides[current_principal] = lambda: principal


@pytest.mark.parametrize("role", [Role.MEMBER, Role.REVIEWER])
def test_only_admins_manage_model_settings(client, role):
    act_as(person(role))
    assert client.get("/admin/models").status_code == 403
    assert client.put("/admin/models/translation", json=PARAMS).status_code == 403
    assert client.delete("/admin/models/translation").status_code == 403
    assert client.post("/admin/models/translation/test", json=PARAMS).status_code == 403


def test_the_overview_shows_defaults_the_allow_list_and_whether_a_key_exists(client):
    body = client.get("/admin/models").json()
    assert body["key_configured"] is True
    assert body["key_name"] == "HERITAGEVOICE_LLM_API_KEY"
    assert body["allowed"] == {"anthropic": list(ALLOWED_MODELS[Provider.ANTHROPIC])}
    (row,) = body["roles"]
    assert (row["role"], row["source"], row["model"]) == (
        "translation",
        "default",
        "claude-sonnet-5-5",
    )


def test_a_missing_key_is_reported_without_revealing_anything(client, monkeypatch):
    monkeypatch.delenv("HERITAGEVOICE_LLM_API_KEY")
    assert client.get("/admin/models").json()["key_configured"] is False


def test_saving_a_setting_is_stored_audited_and_shown(client, engine):
    response = client.put("/admin/models/translation", json=PARAMS)
    assert response.json()["model"] == "claude-haiku-5-5"
    assert response.json()["source"] == "database"
    assert client.get("/admin/models").json()["roles"][0]["temperature"] == 0.2
    with Session(engine) as session:
        entry = session.scalars(select(AuditLogRow)).one()
        stored = ModelSettingRepository(session).get(ModelRole.TRANSLATION)
    assert (entry.actor_sub, entry.action, entry.target, entry.detail) == (
        "admin-1",
        "model:update",
        "model:translation",
        "anthropic/claude-haiku-5-5",
    )
    assert (stored.model, stored.max_retries) == ("claude-haiku-5-5", 2)


@pytest.mark.parametrize(
    "overrides",
    [
        {"model": "gpt-9000"},
        {"model": ""},
        {"provider": "openai"},
        {"temperature": 1.5},
        {"timeout_s": 1},
        {"timeout_s": 1000},
        {"max_retries": 9},
        {"api_key": "sk-anything"},
    ],
    ids=["unknown-model", "empty", "unknown-provider", "hot", "fast", "slow", "retries", "key"],
)
def test_invalid_settings_are_rejected_and_an_api_key_can_never_be_submitted(
    client, engine, overrides
):
    assert client.put("/admin/models/translation", json={**PARAMS, **overrides}).status_code == 422
    with Session(engine) as session:
        assert ModelSettingRepository(session).get(ModelRole.TRANSLATION) is None


def test_an_unknown_role_is_422(client):
    assert client.put("/admin/models/supervisor", json=PARAMS).status_code == 422


def test_resetting_returns_to_the_environment_default(client, engine):
    client.put("/admin/models/translation", json=PARAMS)
    response = client.delete("/admin/models/translation")
    assert (response.json()["source"], response.json()["model"]) == ("default", "claude-sonnet-5-5")
    with Session(engine) as session:
        assert ModelSettingRepository(session).list_all() == []
        actions = [e.action for e in session.scalars(select(AuditLogRow))]
    assert actions == ["model:update", "model:reset"]


class FakeTester:
    def __init__(self, result):
        self.result, self.seen = result, []

    def check(self, params):
        self.seen.append(params)
        return self.result


def test_the_test_button_reports_a_safe_code_and_saves_nothing(client, engine):
    tester = FakeTester(ProbeResult(ok=False, code="bad_key"))
    app.dependency_overrides[get_model_tester] = lambda: tester
    body = client.post("/admin/models/translation/test", json=PARAMS).json()
    assert body == {"ok": False, "code": "bad_key"}
    assert tester.seen[0].model == "claude-haiku-5-5"
    with Session(engine) as session:
        assert ModelSettingRepository(session).list_all() == []
    app.dependency_overrides[get_model_tester] = lambda: FakeTester(ProbeResult(ok=True))
    assert client.post("/admin/models/translation/test", json=PARAMS).json() == {
        "ok": True,
        "code": None,
    }


def test_the_api_key_never_appears_in_any_response(client, api_key):
    app.dependency_overrides[get_model_tester] = lambda: FakeTester(ProbeResult(ok=True))
    responses = [
        client.get("/admin/models"),
        client.put("/admin/models/translation", json=PARAMS),
        client.post("/admin/models/translation/test", json=PARAMS),
        client.delete("/admin/models/translation"),
        client.put("/admin/models/translation", json={**PARAMS, "api_key": api_key}),
    ]
    assert all(api_key not in response.text for response in responses)


def test_the_tester_without_a_key_does_not_call_the_provider():
    tester = AnthropicModelTester(None)
    result = tester.check(ModelParams(**PARAMS))
    assert (result.ok, result.code) == (False, "no_key")
    assert isinstance(tester, ModelTester)


def test_provider_errors_map_to_short_codes():
    response = httpx.Response(401, request=httpx.Request("POST", "http://x"))
    auth = anthropic.AuthenticationError("secret detail", response=response, body=None)
    assert _code_for(auth) == "bad_key"
    assert _code_for(RuntimeError("anything")) == "provider_error"


def test_me_tells_the_ui_who_is_signed_in(client):
    assert client.get("/v1/me").json() == {"user_id": "admin-1", "role": "admin", "communities": []}
    act_as(person(Role.REVIEWER, user_id="r", communities=("c2", "c1")))
    assert client.get("/v1/me").json()["communities"] == ["c1", "c2"]


def test_me_needs_authentication():
    app.dependency_overrides.clear()
    assert TestClient(app).get("/v1/me").status_code in {401, 503}
