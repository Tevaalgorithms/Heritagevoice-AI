"""Fix a draft transcript: the person who uploaded a recording can correct what the computer heard.

A saved correction makes a new draft; nothing becomes searchable until an administrator approves
it. Once a transcript is approved it can no longer be changed here.
"""

import streamlit as st

from frontend.api_client import ApiClient, ApiError, RecordingView, VersionView
from frontend.format import changed_edits, editor_rows
from frontend.messages import message_for

HELP = (
    "Fix any words the computer got wrong, then save. "
    "An administrator checks it before anyone can search it."
)
LOCKED = "This transcript has been approved. Ask an administrator if something needs changing."


def _save(client: ApiClient, recording: RecordingView, edits: dict[str, str]) -> None:
    transcript = recording.transcript
    if transcript is None:
        return
    try:
        client.edit_draft(recording.id, "transcript", transcript.version, edits)
    except ApiError as error:
        st.error(message_for(error))
        return
    st.toast("Saved. Your corrections are waiting for review.")
    st.rerun()


def _table(recording: RecordingView, transcript: VersionView, editable: bool) -> dict[str, str]:
    """Show the segments; return the corrections made so far (none when it is locked)."""
    rows = st.data_editor(
        editor_rows(transcript.segments),
        key=f"transcript-{recording.id}-{transcript.version}",
        hide_index=True,
        disabled=["id", "time"] if editable else True,
    )
    return changed_edits(transcript.segments, list(rows)) if editable else {}


def render_editor(client: ApiClient, recording: RecordingView) -> None:
    """The transcript as a table; its text column is editable while it is still a draft."""
    transcript = recording.transcript
    if transcript is None:
        st.info("No transcript yet.")
        return
    editable = transcript.status == "draft"
    st.caption(f"Version {transcript.version} · {transcript.status}")
    st.caption(HELP if editable else LOCKED)
    edits = _table(recording, transcript, editable)
    key = f"transcript-{recording.id}-{transcript.version}-save"
    if editable and st.button("Save corrections", key=key, disabled=not edits):
        _save(client, recording, edits)
