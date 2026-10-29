import httpx
import pytest

from frontend.api_client import ApiClient, ApiRequestError, ReviewSpec, SegmentView
from frontend.format import changed_edits, editor_rows
from frontend.messages import CODE_MESSAGES, message_for

SEGMENTS = [
    SegmentView(segment_id="s1", start_s=0.0, end_s=2.5, text="வணக்கம்"),
    SegmentView(segment_id="s2", start_s=2.5, end_s=9.0, text="நன்றி"),
]


def client_for(handler):
    return ApiClient("http://api.test", "tok", transport=httpx.MockTransport(handler))


def test_editor_rows_show_id_time_and_text():
    first, _ = editor_rows(SEGMENTS)
    assert first == {"id": "s1", "time": "00:00.0-00:02.5", "text": "வணக்கம்"}


def test_only_changed_non_empty_text_is_sent():
    rows = editor_rows(SEGMENTS)
    rows[0]["text"] = "  வணக்கம் அன்பர்களே  "
    rows[1]["text"] = "   "
    assert changed_edits(SEGMENTS, rows) == {"s1": "வணக்கம் அன்பர்களே"}


def test_unchanged_or_unknown_rows_produce_no_edits():
    rows = editor_rows(SEGMENTS) + [{"id": "s99", "time": "", "text": "ghost"}]
    assert changed_edits(SEGMENTS, rows) == {}


def test_recordings_are_listed_for_the_reviewer():
    def handler(request):
        assert request.url.path == "/v1/recordings"
        item = {"id": "r1", "community_id": "c1", "language": "ta", "status": "review"}
        return httpx.Response(200, json=[item])

    (summary,) = client_for(handler).list_recordings()
    assert (summary.id, summary.status, summary.duration_s) == ("r1", "review", None)


def test_an_edit_is_sent_as_a_patch_with_the_expected_version():
    seen = {}

    def handler(request):
        seen["method"], seen["path"] = request.method, request.url.path
        seen["body"] = request.read()
        return httpx.Response(200, json={"kind": "transcript", "version": 2, "status": "draft"})

    result = client_for(handler).edit_draft("r1", "transcript", 1, {"s1": "fixed"})
    assert (seen["method"], seen["path"]) == ("PATCH", "/v1/recordings/r1/draft")
    assert b'"expected_version":1' in seen["body"].replace(b" ", b"")
    assert (result.version, result.status) == (2, "draft")


def test_review_and_publish_use_the_review_and_publish_endpoints():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/publish"):
            return httpx.Response(200, json={"recording_id": "r1", "status": "published"})
        return httpx.Response(200, json={"kind": "transcript", "version": 1, "status": "approved"})

    client = client_for(handler)
    spec = ReviewSpec(kind="transcript", expected_version=1, approved=True)
    assert client.review("r1", spec).status == "approved"
    assert client.publish("r1") == "published"
    assert paths == ["/v1/recordings/r1/review", "/v1/recordings/r1/publish"]


@pytest.mark.parametrize(
    "code", ["stale_version", "not_reviewable", "transcript_not_approved", "unknown_segment"]
)
def test_review_conflicts_have_plain_messages(code):
    assert code in CODE_MESSAGES
    assert message_for(ApiRequestError(409, code)) == CODE_MESSAGES[code]


def test_a_stale_edit_surfaces_its_code():
    def handler(request):
        return httpx.Response(409, json={"detail": {"code": "stale_version"}})

    with pytest.raises(ApiRequestError) as error:
        client_for(handler).edit_draft("r1", "transcript", 1, {"s1": "x"})
    assert (error.value.status_code, error.value.code) == (409, "stale_version")
