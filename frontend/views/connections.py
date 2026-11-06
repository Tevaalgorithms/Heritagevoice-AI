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
from frontend.spoken import LANGUAGE_CHOICES
from frontend.views.playback import listen_button
from frontend.views.report import report_button

INTRO = (
    "How people, places, songs and customs are connected, as people have reviewed and approved "
    "them. Each connection shows the words in the recording that say it."
)
QUERY = "connections-q"
HEARD = "connections-heard"  # words just heard; put in the box before it is drawn
VOICE_HELP = (
    "Pick your language, record a few words, and the search fills in. The recording is deleted "
    "as soon as it has been understood. It needs no account."
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
        listen_button(play, item.recording_id, key, (item.start_s, item.end_s))
        report_button(client, item.recording_id, key)


def _use_voice(client: ApiClient, language: str, audio: bytes) -> None:
    try:
        with st.spinner("Listening…"):
            heard = client.hear_search(audio, language)
    except ApiError as error:
        st.error(message_for(error))
        return
    if heard:
        st.session_state[HEARD] = heard
        st.rerun()
    st.warning("I could not make out any words. Try again, a little closer and slower.")


def _voice(client: ApiClient) -> None:
    """Say a name or idea instead of typing it. The recording is deleted as soon as it is heard."""
    with st.expander("Search by voice", icon=":material/mic:"):
        st.caption(VOICE_HELP)
        label = st.selectbox("Language you will speak", list(LANGUAGE_CHOICES), index=0)
        recorded = st.audio_input("Say a name or idea", key="connections-voice")
        if st.button("Search with my voice", disabled=recorded is None) and recorded is not None:
            _use_voice(client, LANGUAGE_CHOICES[str(label)], recorded.getvalue())


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
