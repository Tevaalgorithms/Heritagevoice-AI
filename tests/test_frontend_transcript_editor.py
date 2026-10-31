import httpx
from streamlit.testing.v1 import AppTest

from frontend.api_client import ApiClient
from frontend.views.transcript_editor import HELP, LOCKED


def _page():
    import streamlit as st  # noqa: PLC0415

    from frontend.api_models import RecordingView, SegmentView, VersionView  # noqa: PLC0415
    from frontend.views.transcript_editor import render_editor  # noqa: PLC0415

    class Client:
        def edit_draft(self, *args):
            raise AssertionError("nothing was edited")

    segments = [SegmentView(segment_id="s1", start_s=0, end_s=1, text="hello", speaker=None)]
    version = VersionView(version=1, status=st.session_state.status, segments=segments)
    render_editor(
        Client(),  # type: ignore[arg-type]
        RecordingView(
            id="r1", community_id="c1", status="review", language="en", transcript=version
        ),
    )


def run(status):
    app = AppTest.from_function(_page, default_timeout=30)
    app.session_state["status"] = status
    return app.run()


def test_a_draft_transcript_can_be_corrected_but_not_saved_until_something_changes():
    app = run("draft")
    assert not app.exception
    assert HELP in [c.value for c in app.caption]
    (save,) = app.button
    assert save.disabled is True


def test_an_approved_transcript_is_locked_and_offers_no_save():
    app = run("approved")
    assert not app.exception
    assert LOCKED in [c.value for c in app.caption]
    assert len(app.button) == 0


def test_corrections_are_sent_as_a_new_draft_of_the_transcript():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, request.content))
        return httpx.Response(200, json={"kind": "transcript", "version": 2, "status": "draft"})

    client = ApiClient("http://api.test", "tok", transport=httpx.MockTransport(handler))
    client.edit_draft("r1", "transcript", 1, {"s1": "fixed"})
    assert seen[0][:2] == ("PATCH", "/v1/recordings/r1/draft")
    assert b'"expected_version":1' in seen[0][2]
    assert b'"text":"fixed"' in seen[0][2]
