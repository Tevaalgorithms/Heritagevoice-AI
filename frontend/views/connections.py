"""Connections: how people, places, songs and customs are linked, as people have reviewed them.

Each connection shows the words in the recording that say it, where they are, and a Listen button.
It works with or without an account: the server applies the same rules as the Library, so a
visitor sees only what was shared publicly and a signed-in reader also sees their own groups'.
"""

import streamlit as st

from app.languages import BY_CODE
from frontend import theme
from frontend.api_client import ApiClient, ApiError
from frontend.api_models import ConnectionItem
from frontend.credit import origin_line
from frontend.format import format_time
from frontend.kinds import label_for
from frontend.messages import message_for
from frontend.relations import headline_html
from frontend.views.playback import listen_button
from frontend.views.report import report_button

INTRO = (
    "How people, places, songs and customs are connected, as people have reviewed and approved "
    "them. Each connection shows the words in the recording that say it."
)
EMPTY = (
    "No connections to show yet. A connection appears here after a person has reviewed and "
    "approved it, and only from recordings you may read."
)


def _heading(item: ConnectionItem) -> str:
    language = BY_CODE.get(item.language)
    spoken = language.native_name if language else item.language
    return f"{label_for(item.heritage_kind)} · {spoken}" if item.heritage_kind else "Recording"


def _origin(item: ConnectionItem) -> str:
    credit = item.credit
    return origin_line(
        item.added,
        credit.name if credit else None,
        credit.source_kind if credit else None,
        credit.source_note if credit else None,
    )


def _card(client: ApiClient, item: ConnectionItem) -> None:
    play = client.recording_media if client.signed_in else client.public_recording_media
    with theme.card(f"conn-{item.assertion_id}"):
        st.markdown(headline_html(item.subject, item.relation, item.object), unsafe_allow_html=True)
        for notice in item.notices:
            st.warning(notice, icon=":material/health_and_safety:")
        st.markdown(theme.passage_html(item.passage), unsafe_allow_html=True)
        span = f"{format_time(item.start_s)} to {format_time(item.end_s)}"
        st.caption(f"Said in {_heading(item)} · {span}")
        origin = _origin(item)
        if origin:
            st.caption(origin)
        listen_button(
            play, item.recording_id, f"conn-{item.assertion_id}", (item.start_s, item.end_s)
        )
        report_button(client, item.recording_id, f"conn-{item.assertion_id}")


def render(client: ApiClient) -> None:
    """The Connections page: search a name or idea, or see the newest connections."""
    theme.page_header("Connections", INTRO, "connections")
    text = st.text_input(
        "Search a name or idea",
        placeholder="For example: humility, a place, a song",
        max_chars=100,
        key="connections-q",
    )
    try:
        items = client.connections(text.strip()).items
    except ApiError as error:
        st.error(message_for(error))
        return
    if not items:
        st.info(EMPTY if not text.strip() else "Nothing matched that search.")
        return
    st.caption(f"{len(items)} shown")
    for item in items:
        _card(client, item)
