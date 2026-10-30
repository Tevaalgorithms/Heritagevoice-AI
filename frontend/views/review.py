"""Review page: compare transcript and translation, edit, approve or reject, then publish.

Playing the audio next to each segment arrives with segment 10 (media access).
"""

import streamlit as st

from frontend import theme
from frontend.api_client import (
    ApiClient,
    ApiError,
    RecordingSummary,
    RecordingView,
    ReviewSpec,
    VersionView,
)
from frontend.format import changed_edits, editor_rows
from frontend.kinds import label_for
from frontend.messages import message_for

REVIEWABLE = {"review", "published"}


def _label(recording: RecordingSummary) -> str:
    kind = label_for(recording.heritage_kind)
    return f"{kind} · {recording.id[:8]} · {recording.language} · {recording.status}"


def _act(action: object, success: str) -> None:
    """Run a client call, show the result, and reload on success."""
    try:
        action()  # type: ignore[operator]
    except ApiError as error:
        st.error(message_for(error))
        return
    st.success(success)
    st.rerun()


def _version_panel(client: ApiClient, recording: RecordingView, kind: str) -> None:
    version: VersionView | None = getattr(recording, kind)
    st.subheader(kind.capitalize())
    if version is None:
        st.info(f"No {kind} yet.")
        return
    st.caption(f"Version {version.version} · {version.status}")
    key = f"{recording.id}-{kind}-{version.version}"
    rows = st.data_editor(
        editor_rows(version.segments),
        key=key,
        hide_index=True,
        disabled=["id", "time"],
    )
    edits = changed_edits(version.segments, list(rows))
    save, approve, reject = st.columns(3)
    if save.button("Save as new draft", key=f"{key}-save", disabled=not edits):
        _act(lambda: client.edit_draft(recording.id, kind, version.version, edits), "Saved.")
    decision = ReviewSpec(kind=kind, expected_version=version.version, approved=True)
    if approve.button("Approve", key=f"{key}-ok", disabled=version.status != "draft"):
        _act(lambda: client.review(recording.id, decision), "Approved.")
    rejection = decision.model_copy(update={"approved": False})
    if reject.button("Reject", key=f"{key}-no", disabled=version.status != "draft"):
        _act(lambda: client.review(recording.id, rejection), "Rejected.")


def _review_recording(client: ApiClient, recording_id: str) -> None:
    try:
        recording = client.get_recording(recording_id)
    except ApiError as error:
        st.error(message_for(error))
        return
    st.caption("Audio playback next to each segment arrives with segment 10.")
    left, right = st.columns(2)
    with left:
        _version_panel(client, recording, "transcript")
    with right:
        _version_panel(client, recording, "translation")
    if st.button("Publish approved transcript", disabled=recording.status != "review"):
        _act(lambda: client.publish(recording.id), "Published.")


def _load_recordings(client: ApiClient) -> list[RecordingSummary] | None:
    try:
        return [r for r in client.list_recordings() if r.status in REVIEWABLE]
    except ApiError as error:
        st.error(message_for(error))
        return None


def render(client: ApiClient) -> None:
    theme.page_header(
        "Review",
        "Check each transcript and translation. Only approved work becomes part of the collection.",
        "review",
    )
    recordings = _load_recordings(client)
    if not recordings:
        if recordings is not None:
            st.info("Nothing is waiting for review.")
        return
    chosen = st.selectbox("Recording", recordings, format_func=_label)
    if chosen is not None:
        _review_recording(client, chosen.id)
