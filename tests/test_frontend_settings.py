import httpx
import pytest

from frontend.api_client import ApiClient, ApiRequestError, ModelParamsSpec, NewModelSpec
from frontend.messages import PROBE_MESSAGES, message_for, probe_message

PARAMS = ModelParamsSpec(provider="anthropic", model="claude-haiku-5-5", temperature=0.2)
VIEW = {
    "role": "translation",
    "provider": "anthropic",
    "model": "claude-haiku-5-5",
    "temperature": 0.2,
    "timeout_s": 30.0,
    "max_retries": 2,
    "source": "database",
}


def client_for(handler):
    return ApiClient("http://api.test", "tok", transport=httpx.MockTransport(handler))


def test_me_tells_the_ui_the_role():
    def handler(request):
        assert request.url.path == "/v1/me"
        return httpx.Response(200, json={"user_id": "u1", "role": "admin", "communities": []})

    assert client_for(handler).me().role == "admin"


CATALOG = [
    {
        "model_id": "claude-haiku-5-5",
        "provider": "anthropic",
        "key_name": "HERITAGEVOICE_LLM_API_KEY",
        "status": "active",
        "key_configured": True,
    }
]


def test_the_overview_is_parsed_and_carries_no_key_value():
    def handler(request):
        return httpx.Response(
            200,
            json={"catalog": CATALOG, "roles": [{**VIEW, "source": "default", "fallbacks": []}]},
        )

    overview = client_for(handler).model_settings()
    assert overview.catalog[0].key_configured is True
    assert overview.catalog[0].key_name == "HERITAGEVOICE_LLM_API_KEY"
    assert overview.roles[0].source == "default"
    assert overview.roles[0].fallbacks == []


def test_adding_a_model_and_changing_its_status_use_the_catalogue_endpoints():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, request.read()))
        return httpx.Response(200, json=CATALOG[0])

    client = client_for(handler)
    client.add_model(NewModelSpec(model_id="m-1", provider="anthropic", key_name="SOME_KEY"))
    client.set_model_status("m-1", "disabled")
    assert [(m, p) for m, p, _ in seen] == [
        ("POST", "/admin/models/catalog"),
        ("PUT", "/admin/models/catalog/m-1"),
    ]
    assert b"SOME_KEY" in seen[0][2]
    assert b'"disabled"' in seen[1][2]


def test_saving_sends_the_fallbacks_in_order():
    seen = {}

    def handler(request):
        seen["body"] = request.read()
        return httpx.Response(200, json=VIEW)

    params = ModelParamsSpec(provider="anthropic", model="a", fallbacks=["b", "c"])
    client_for(handler).save_model_setting("translation", params)
    assert b'"fallbacks":["b","c"]' in seen["body"].replace(b" ", b"")


def test_saving_sends_only_model_parameters_never_a_key():
    seen = {}

    def handler(request):
        seen["method"], seen["path"], seen["body"] = (
            request.method,
            request.url.path,
            request.read(),
        )
        return httpx.Response(200, json=VIEW)

    result = client_for(handler).save_model_setting("translation", PARAMS)
    assert (seen["method"], seen["path"]) == ("PUT", "/admin/models/translation")
    assert b"api_key" not in seen["body"]
    assert b"key" not in seen["body"].lower()
    assert result.model == "claude-haiku-5-5"


def test_reset_and_probe_use_their_endpoints():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/test"):
            return httpx.Response(200, json={"ok": False, "code": "bad_key"})
        return httpx.Response(200, json={**VIEW, "source": "default"})

    client = client_for(handler)
    assert client.reset_model_setting("translation").source == "default"
    probe = client.probe_model_setting("translation", PARAMS)
    assert (probe.ok, probe.code) == (False, "bad_key")
    assert seen == [
        ("DELETE", "/admin/models/translation"),
        ("POST", "/admin/models/translation/test"),
    ]


@pytest.mark.parametrize("code", sorted(PROBE_MESSAGES))
def test_every_probe_code_has_a_plain_message(code):
    assert probe_message(code) == PROBE_MESSAGES[code]


def test_unknown_probe_codes_get_a_generic_message():
    assert probe_message("surprise") == "The test failed."
    assert probe_message(None) == "The test failed."


def test_non_admins_get_a_clear_refusal():
    def handler(request):
        return httpx.Response(403, json={"detail": "Not permitted"})

    with pytest.raises(ApiRequestError) as error:
        client_for(handler).model_settings()
    assert error.value.status_code == 403
    assert "could not be completed" in message_for(error.value)
