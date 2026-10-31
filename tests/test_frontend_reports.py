import httpx
import pytest

from app.models.records import ReportReason
from frontend.api_client import ApiClient, ApiRequestError
from frontend.messages import message_for
from frontend.views.report import REASONS


def client_for(handler, token="tok"):
    return ApiClient("http://api.test", token, transport=httpx.MockTransport(handler))


def test_every_reason_the_server_accepts_has_a_plain_label():
    assert set(REASONS) == {reason.value for reason in ReportReason}


def test_a_visitor_reports_without_a_token_and_a_member_with_one():
    seen = []

    def handler(request):
        seen.append((request.url.path, request.headers.get("authorization")))
        return httpx.Response(201, json={"id": "x"})

    client_for(handler, token=None).report_item("r1", "private", "")
    client_for(handler).report_item("r1", "private", "please")
    assert seen == [("/v1/public/report", None), ("/v1/reports", "Bearer tok")]


def test_an_empty_note_is_not_sent():
    sent = {}

    def handler(request):
        sent["body"] = request.content
        return httpx.Response(201, json={"id": "x"})

    client_for(handler).report_item("r1", "other", "")
    assert b'"note":null' in sent["body"]


def test_admins_list_and_decide_reports():
    seen = []
    item = {
        "id": "x",
        "recording_id": "r1",
        "reason": "private",
        "note": None,
        "reporter": "a visitor",
        "heritage_kind": "story",
        "language": "ta",
        "community": "c1",
        "recording_status": "published",
        "opening": "words",
        "reports_for_recording": 2,
    }

    def handler(request):
        seen.append((request.method, request.url.path, request.content))
        return httpx.Response(200, json=[item] if request.method == "GET" else {})

    client = client_for(handler)
    assert client.reports()[0].reports_for_recording == 2
    client.decide_report("x", True)
    client.decide_report("x", False)
    assert b'"action":"take_down"' in seen[1][2]
    assert b'"action":"dismiss"' in seen[2][2]


def test_a_rate_limited_reporter_is_told_to_wait():
    def handler(request):
        return httpx.Response(429, json={"detail": {"code": "rate_limited"}})

    with pytest.raises(ApiRequestError) as caught:
        client_for(handler).report_item("r1", "private", "")
    assert "wait" in message_for(caught.value)
