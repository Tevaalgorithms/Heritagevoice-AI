"""Report this item: anyone who can read a recording can say it should not be shared.

It works with or without an account. The report goes to an administrator, who decides; the
person who shared the recording is never told who reported it.
"""

import streamlit as st

from frontend.api_client import ApiClient, ApiError
from frontend.messages import message_for

REASONS = {
    "private": "It is private or should not be shared",
    "harmful": "It is harmful or offensive",
    "health": "It gives health advice that could hurt someone",
    "copyright": "It belongs to someone else",
    "other": "Something else",
}
THANKS = "Thank you. An administrator will look at it."


def _send(client: ApiClient, recording_id: str, reason: str, note: str) -> None:
    try:
        client.report_item(recording_id, reason, note.strip())
    except ApiError as error:
        st.error(message_for(error))
        return
    st.success(THANKS)


def report_button(client: ApiClient, recording_id: str, key: str) -> None:
    """A small 'Report this item' control that opens a short form."""
    with st.popover("Report this item", icon=":material/flag:"):
        with st.form(f"report-{key}", border=False):
            reason = st.selectbox("What is wrong?", list(REASONS), format_func=REASONS.__getitem__)
            note = st.text_area("Tell us more (optional)", max_chars=500)
            sent = st.form_submit_button("Send report")
        if sent:
            _send(client, recording_id, str(reason), note)
