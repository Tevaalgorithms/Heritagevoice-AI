from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from frontend.api_client import (
    ApiClient,
    ApiNotConfiguredError,
    ApiNotReadyError,
    ApiRequestError,
    ApiUnavailableError,
)
from frontend.messages import message_for

APP = Path(__file__).resolve().parents[1] / "frontend" / "streamlit_app.py"


def client_for(handler, token="tok"):
    return ApiClient("http://api.test", token, transport=httpx.MockTransport(handler))


def test_health_and_ready_are_parsed():
    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "mode": "scaffold"})
        return httpx.Response(503, json={"ready": False, "checks": {"postgres": "failed"}})

    client = client_for(handler)
    assert client.health().status == "ok"
    report = client.ready()
    assert (report.ready, report.checks) == (False, {"postgres": "failed"})


def test_query_sends_the_bearer_token_and_parses_the_answer():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"status": "answered", "answer": "Hi", "request_id": "r1"})

    result = client_for(handler).query("Who?")
    assert (seen["auth"], result.answer) == ("Bearer tok", "Hi")


def test_query_without_a_token_never_calls_the_api():
    def handler(request):
        raise AssertionError("must not be called")

    with pytest.raises(ApiNotConfiguredError):
        client_for(handler, token=None).query("Who?")


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(503, json={}), ApiNotReadyError),
        (httpx.Response(401, json={}), ApiRequestError),
        (httpx.Response(500, json={}), ApiRequestError),
    ],
)
def test_error_responses_become_typed_errors(response, error):
    with pytest.raises(error):
        client_for(lambda request: response).query("Who?")


def test_connection_failures_become_unavailable():
    def handler(request):
        raise httpx.ConnectError("down")

    with pytest.raises(ApiUnavailableError):
        client_for(handler).health()


@pytest.mark.parametrize(
    ("error", "fragment"),
    [
        (ApiNotConfiguredError(), "HERITAGEVOICE_DEV_API_TOKEN"),
        (ApiUnavailableError(), "unavailable"),
        (ApiNotReadyError(), "not ready"),
        (ApiRequestError(500), "could not be completed"),
        (ApiRequestError(401), "sign-in has expired"),
    ],
)
def test_every_error_has_a_plain_message(error, fragment):
    assert fragment in message_for(error)


def test_the_app_renders_its_menu_and_says_when_the_api_is_unavailable(monkeypatch):
    monkeypatch.setenv("HERITAGEVOICE_API_URL", "http://127.0.0.1:1")
    monkeypatch.delenv("HERITAGEVOICE_DEV_API_TOKEN", raising=False)
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    assert [h.value for h in app.header] == ["Library"]
    assert any("unavailable" in e.value for e in app.error)


def test_a_visitor_gets_a_sign_in_button_at_the_top_and_no_error(monkeypatch):
    monkeypatch.setenv("HERITAGEVOICE_API_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("HERITAGEVOICE_COGNITO_REGION", "us-west-2")
    monkeypatch.setenv("HERITAGEVOICE_COGNITO_USER_POOL_ID", "us-west-2_TEST")
    monkeypatch.setenv("HERITAGEVOICE_COGNITO_APP_CLIENT_ID", "client")
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    assert any(b.key == "hv-header-signin" for b in app.button)
    assert any(b.key == "hv-header-create" for b in app.button)
