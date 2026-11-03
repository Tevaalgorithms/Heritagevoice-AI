"""The public home page: visitors search with no account, and no token is ever sent."""

from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

from frontend.api_client import ApiClient, LibrarySpec
from frontend.views.home import CREATE_LABEL, OPEN_NOTE, SIGN_IN_LABEL

APP = Path(__file__).resolve().parents[1] / "frontend" / "streamlit_app.py"
ITEM = {
    "evidence_id": "e1",
    "recording_id": "r1",
    "heritage_kind": "song",
    "language": "ta",
    "view": "original",
    "passage": "வணக்கம்",
    "start_s": 0.0,
    "end_s": 4.0,
    "notices": [],
    "community": None,
}


def test_a_visitors_search_goes_to_the_open_endpoint_with_no_credentials():
    seen = {}

    def handler(request):
        seen["path"], seen["query"], seen["auth"] = (
            request.url.path,
            dict(request.url.params),
            request.headers.get("authorization"),
        )
        return httpx.Response(200, json={"items": [ITEM]})

    client = ApiClient("http://api.test", None, transport=httpx.MockTransport(handler))
    result = client.public_library(LibrarySpec(q="water", language="ta", limit=10))
    assert seen["path"] == "/v1/public/library"
    assert seen["query"] == {"q": "water", "language": "ta", "view": "original", "limit": "10"}
    assert seen["auth"] is None
    assert result.items[0].recording_id == "r1"


def test_even_a_client_that_has_a_token_sends_none_to_the_open_endpoint():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"items": []})

    client = ApiClient("http://api.test", "secret-token", transport=httpx.MockTransport(handler))
    client.public_library(LibrarySpec())
    assert seen["auth"] is None


def visitor_app(monkeypatch):
    monkeypatch.setenv("HERITAGEVOICE_API_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("HERITAGEVOICE_COGNITO_REGION", "us-west-2")
    monkeypatch.setenv("HERITAGEVOICE_COGNITO_USER_POOL_ID", "us-west-2_TEST")
    monkeypatch.setenv("HERITAGEVOICE_COGNITO_APP_CLIENT_ID", "client")
    monkeypatch.delenv("HERITAGEVOICE_DEV_API_TOKEN", raising=False)
    return AppTest.from_file(str(APP), default_timeout=20).run()


def test_a_visitor_sees_the_search_and_the_sign_in_choice_without_an_error(monkeypatch):
    app = visitor_app(monkeypatch)
    assert not app.exception
    text = " ".join(m.value for m in app.markdown)
    assert "Search the shared heritage" in text
    labels = [b.label for b in app.button]
    assert SIGN_IN_LABEL in labels
    assert CREATE_LABEL in labels
    assert any(OPEN_NOTE in c.value for c in app.caption)


def test_a_visitor_is_never_shown_the_signed_in_sections(monkeypatch):
    app = visitor_app(monkeypatch)
    page_text = " ".join(m.value for m in app.markdown) + " ".join(c.value for c in app.caption)
    for private in ("Add a recording", "Settings", "Review", "Sign out"):
        assert private not in [b.label for b in app.button]
        assert f"**{private}**" not in page_text


def test_a_signed_in_account_the_server_does_not_know_sees_the_waiting_screen(monkeypatch):
    """403 from /v1/me means: signed in, but not approved yet."""
    from frontend.account import AwaitingApprovalError, current_role  # noqa: PLC0415
    from frontend.api_errors import ApiRequestError  # noqa: PLC0415

    class Client:
        def __init__(self, status):
            self.status = status

        def me(self):
            raise ApiRequestError(self.status)

    import pytest  # noqa: PLC0415

    with pytest.raises(AwaitingApprovalError):
        current_role(Client(403))
    assert current_role(Client(500)) is None


def test_an_expired_sign_in_is_reported_not_hidden():
    """401 from /v1/me means the access token ran out: ask the person to sign in again."""
    import pytest  # noqa: PLC0415

    from frontend.account import SessionExpiredError, current_role  # noqa: PLC0415
    from frontend.api_errors import ApiRequestError  # noqa: PLC0415
    from frontend.messages import SESSION_EXPIRED, message_for  # noqa: PLC0415

    class Client:
        def me(self):
            raise ApiRequestError(401)

    with pytest.raises(SessionExpiredError):
        current_role(Client())
    assert message_for(ApiRequestError(401)) == SESSION_EXPIRED


def test_the_admin_people_calls_go_to_the_admin_endpoints_with_the_token():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, request.headers.get("authorization")))
        body = [{"sub": "s1", "email": "a@example.org", "created": "2026-10-30"}]
        return httpx.Response(200, json=body if request.method == "GET" else {})

    client = ApiClient("http://api.test", "tok", transport=httpx.MockTransport(handler))
    assert client.signups()[0].email == "a@example.org"
    client.approve_signup("s1", ["c1"])
    client.decline_signup("s1")
    client.invite_user("n@example.org", "admin", ["c1"])
    assert seen == [
        ("GET", "/admin/signups", "Bearer tok"),
        ("POST", "/admin/signups/s1/approve", "Bearer tok"),
        ("POST", "/admin/signups/s1/decline", "Bearer tok"),
        ("POST", "/admin/users", "Bearer tok"),
    ]
