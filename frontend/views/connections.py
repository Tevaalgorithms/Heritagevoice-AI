"""Connections: how people, places, songs and customs are linked, as people have reviewed them.

Each connection shows the words in the recording that say it, where they are, and a Listen button.
It works with or without an account: the server applies the same rules as the Library, so a
visitor sees only what was shared publicly and a signed-in reader also sees their own groups'.
"""

import streamlit as st

from app.languages import BY_CODE
from frontend import theme, voice
from frontend.api_client import ApiClient, ApiError
from frontend.api_models import ConnectionItem
from frontend.credit import origin_line, voice_note
from frontend.format import format_time
from frontend.kinds import label_for
from frontend.messages import message_for
from frontend.relations import headline_html
from frontend.spoken import LANGUAGE_CHOICES
from frontend.views.playback import Moment, listen_button
from frontend.views.report import report_button

INTRO = (
    "How people, places, songs and customs are connected, as people have reviewed and approved "
    "them. Each connection shows the words in the recording that say it."
)
QUERY = "connections-q"
HEARD = "connections-heard"  # words just heard; put in the box before it is drawn
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


def _english(item: ConnectionItem) -> None:
    """The relationship and the words that say it, in English, where there is something to show."""
    if not item.has_english:
        st.caption("There is no English version of this one yet.")
        return
    st.markdown(
        headline_html(
            item.subject_en or item.subject, item.relation, item.object_en or item.object
        ),
        unsafe_allow_html=True,
    )
    if item.translation:
        st.markdown(theme.passage_html(item.translation), unsafe_allow_html=True)


def _card(client: ApiClient, item: ConnectionItem) -> None:
    play = client.recording_media if client.signed_in else client.public_recording_media
    key = f"conn-{item.assertion_id}"
    with theme.card(key):
        st.markdown(headline_html(item.subject, item.relation, item.object), unsafe_allow_html=True)
        for notice in item.notices:
            st.warning(notice, icon=":material/health_and_safety:")
        st.markdown(theme.passage_html(item.passage), unsafe_allow_html=True)
        span = f"{format_time(item.start_s)} to {format_time(item.end_s)}"
        st.caption(f"Said in {_heading(item)} · {span}")
        origin = _origin(item)
        if origin:
            st.caption(origin)
        if st.toggle("English", key=f"{key}-en", help="Show this connection in English"):
            _english(item)
        moment = Moment(item.start_s, item.end_s, voice_note(item.credit))
        listen_button(play, item.recording_id, key, moment)
        report_button(client, item.recording_id, key)


def _voice(client: ApiClient) -> None:
    """Say a name or idea instead of typing it. The words appear in the box as soon as the
    recording stops, and the search runs from them. The recording is deleted once understood."""
    with st.expander("Search by voice", icon=":material/mic:"):
        st.caption(voice.HELP)
        label = st.selectbox("Language you will speak", list(LANGUAGE_CHOICES), index=0)
        recorded = st.audio_input("Say a name or idea, then stop", key="connections-voice")
        if recorded is not None:
            voice.hear_once(client, str(label), recorded.getvalue(), "connections")


def _search() -> str:
    """The search box with a Search button; returns what to look for."""
    heard = st.session_state.pop(HEARD, None)
    if heard:
        st.session_state[QUERY] = heard  # allowed here: the box is not drawn yet in this run
    with st.form("connections-search", border=False):
        box, button = st.columns([5, 1], vertical_alignment="bottom")
        text = box.text_input(
            "Search a name or idea",
            placeholder="In Tamil or English: பணிவு, humility, a place, a song",
            max_chars=100,
            key=QUERY,
        )
        button.form_submit_button("Search", icon=":material/search:", type="primary")
    return text.strip()


def render(client: ApiClient) -> None:
    """The Connections page: search a name or idea, or see the newest connections."""
    theme.page_header("Connections", INTRO, "connections")
    text = _search()
    _voice(client)
    try:
        items = client.connections(text).items
    except ApiError as error:
        st.error(message_for(error))
        return
    if not items:
        st.info(EMPTY if not text else "Nothing matched that search.")
        return
    st.caption(f"{len(items)} shown")
    for item in items:
        _card(client, item)
