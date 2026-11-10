import httpx
import pytest

from frontend.api_client import (
    ApiClient,
    ApiRequestError,
    SegmentView,
    UploadSpec,
)
from frontend.format import failure_message, format_time, progress_for, segment_rows
from frontend.messages import CODE_MESSAGES, message_for

SPEC = UploadSpec(data=b"RIFFxxxxWAVE", language="ta", community_id="c1", consent_id="consent-1")


def client_for(handler):
    return ApiClient("http://api.test", "tok", transport=httpx.MockTransport(handler))


def test_an_upload_is_sent_as_multipart_with_the_key_and_a_generic_file_name():
    seen = {}

    def handler(request):
        seen["headers"] = request.headers
        seen["body"] = request.read()
        return httpx.Response(201, json={"recording_id": "r1", "job_id": "j1"})

    result = client_for(handler).upload_recording(SPEC, "key-00000001")
    assert (result.recording_id, result.job_id) == ("r1", "j1")
    assert seen["headers"]["authorization"] == "Bearer tok"
    assert seen["headers"]["idempotency-key"] == "key-00000001"
    assert seen["headers"]["content-type"].startswith("multipart/form-data")
    assert b'filename="recording"' in seen["body"]
    assert b'name="community_id"' in seen["body"]


def test_api_error_codes_are_kept_for_friendly_messages():
    def handler(request):
        return httpx.Response(415, json={"detail": {"code": "unsupported_type"}})

    with pytest.raises(ApiRequestError) as error:
        client_for(handler).upload_recording(SPEC, "key-00000001")
    assert (error.value.status_code, error.value.code) == (415, "unsupported_type")
    assert "supported audio format" in message_for(error.value)


def test_errors_without_a_code_fall_back_to_the_generic_message():
    assert "could not be completed" in message_for(ApiRequestError(500))
    assert "could not be completed" in message_for(ApiRequestError(422, None))


@pytest.mark.parametrize("code", sorted(CODE_MESSAGES))
def test_every_upload_error_code_has_a_message(code):
    assert message_for(ApiRequestError(400, code)) == CODE_MESSAGES[code]


def test_job_and_recording_views_are_parsed():
    def handler(request):
        if request.url.path.startswith("/v1/jobs"):
            return httpx.Response(
                200,
                json={
                    "job_id": "j1",
                    "status": "review",
                    "stage": "transcribe",
                    "error": None,
                    "recording_id": "r1",
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "r1",
                "community_id": "c1",
                "language": "ta",
                "status": "review",
                "duration_s": 2.0,
                "transcript": {
                    "version": 1,
                    "status": "draft",
                    "segments": [
                        {"segment_id": "s1", "start_s": 0.0, "end_s": 1.5, "text": "vanakkam"}
                    ],
                },
                "translation": None,
            },
        )

    client = client_for(handler)
    assert client.get_job("j1").stage == "transcribe"
    recording = client.get_recording("r1")
    assert (recording.transcript.version, recording.translation) == (1, None)


@pytest.mark.parametrize(
    ("seconds", "text"), [(0, "00:00.0"), (9.5, "00:09.5"), (75.25, "01:15.2"), (3601, "60:01.0")]
)
def test_times_are_shown_as_minutes_and_seconds(seconds, text):
    assert format_time(seconds) == text


def test_segments_become_table_rows():
    rows = segment_rows(
        [SegmentView(segment_id="s1", start_s=0, end_s=2, text="வணக்கம்", speaker="a")]
    )
    assert rows == [{"From": "00:00.0", "To": "00:02.0", "Speaker": "a", "Text": "வணக்கம்"}]


@pytest.mark.parametrize(
    ("status", "stage", "fraction"),
    [("queued", None, 0.1), ("processing", "transcribe", 0.7), ("review", "transcribe", 1.0)],
)
def test_progress_follows_the_job_stage(status, stage, fraction):
    assert progress_for(status, stage)[0] == fraction


def test_failures_get_safe_plain_messages():
    assert "speech service" in failure_message("asr")
    assert "consent" in failure_message("consent")
    assert "administrator" in failure_message("anything-else")
    assert "administrator" in failure_message(None)


def test_discarding_a_recording_sends_a_delete_for_that_recording():
    seen = {}

    def handler(request):
        seen["call"] = (request.method, request.url.path, request.headers["authorization"])
        return httpx.Response(204)

    client_for(handler).discard_recording("r1")
    assert seen["call"] == ("DELETE", "/v1/recordings/r1", "Bearer tok")


@pytest.mark.parametrize("code", ["already_shared", "still_processing"])
def test_a_refused_discard_says_why_in_plain_words(code):
    def handler(request):
        return httpx.Response(409, json={"detail": {"code": code}})

    with pytest.raises(ApiRequestError) as raised:
        client_for(handler).discard_recording("r1")
    assert message_for(raised.value) == CODE_MESSAGES[code]
    assert "Someone else" not in message_for(raised.value)


def _discard_script():
    import streamlit as st  # noqa: PLC0415

    from frontend.api_client import RecordingSummary  # noqa: PLC0415
    from frontend.views.upload import _discard_control  # noqa: PLC0415

    class Client:
        def discard_recording(self, recording_id):
            st.session_state["deleted"] = recording_id

    summary = RecordingSummary(id="r1", community_id="c1", language="ta", status="review")
    _discard_control(Client(), summary)  # type: ignore[arg-type]


def test_discarding_asks_first_and_deletes_only_after_a_yes():
    from streamlit.testing.v1 import AppTest  # noqa: PLC0415

    app = AppTest.from_function(_discard_script).run()
    assert not app.exception
    assert [b.label for b in app.button] == ["Discard this recording"]
    app.button[0].click().run()
    assert "cannot be undone" in app.warning[0].value
    assert "deleted" not in app.session_state
    app.button(key="discard-r1-yes").click().run()
    assert app.session_state["deleted"] == "r1"


def test_keeping_the_recording_goes_back_to_the_first_button():
    from streamlit.testing.v1 import AppTest  # noqa: PLC0415

    app = AppTest.from_function(_discard_script).run()
    app.button[0].click().run()
    app.button(key="discard-r1-no").click().run()
    assert [b.label for b in app.button] == ["Discard this recording"]
    assert "deleted" not in app.session_state
