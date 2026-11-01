"""Library page: browse or search what you may read, in the language you choose.

Everything listed has been approved by an admin and shared by its community. The server decides
what each person may see; this page only asks and displays. Remedies arrive with a notice that
is always shown next to the passage.
"""

from collections.abc import Callable

import streamlit as st

from app.languages import BY_CODE, LANGUAGES
from app.models.groups import OPEN_COMMUNITY
from frontend import theme
from frontend.api_client import ApiClient, ApiError, LibraryItem, LibraryResult, LibrarySpec
from frontend.format import format_time
from frontend.kinds import KINDS, label_for
from frontend.messages import message_for
from frontend.views.playback import Fetch, listen_button
from frontend.views.report import report_button

ANY = "Any"
VIEWS = {"Original language": "original", "English translation": "translation"}


def _language_options() -> dict[str, str]:
    options = {ANY: ""}
    options.update({f"{lang.name} · {lang.native_name}": lang.code for lang in LANGUAGES})
    return options


def _kind_options() -> dict[str, str]:
    options = {ANY: ""}
    options.update({f"{kind.icon} {kind.label}": kind.key for kind in KINDS})
    return options


def _filters() -> LibrarySpec:
    """The search box and the choices that narrow it."""
    with st.form("library-search", border=False):
        query = st.text_input(
            "Search",
            placeholder="Search by words, in any language",
            label_visibility="collapsed",
        )
        languages, kinds, view = st.columns(3)
        language = languages.selectbox("Language spoken", list(_language_options()))
        kind = kinds.selectbox("Kind", list(_kind_options()))
        read_as = view.radio("Read in", list(VIEWS), horizontal=False)
        st.form_submit_button("Search", icon=":material/search:", type="primary")
    return LibrarySpec(
        q=query.strip(),
        language=_language_options()[str(language)],
        kind=_kind_options()[str(kind)],
        view=VIEWS[str(read_as)],
    )


def _source(community: str) -> str:
    if community == OPEN_COMMUNITY:
        return " · shared openly"
    return f" · from the {community} community" if community else ""


def _heading(item: LibraryItem) -> str:
    language = BY_CODE.get(item.language)
    spoken = language.native_name if language else item.language
    source = _source(item.community)
    return f"{label_for(item.heritage_kind)} · {spoken}{source}"


def _card(client: ApiClient, play: Fetch, item: LibraryItem) -> None:
    with st.container(border=True):
        st.markdown(f"**{_heading(item)}**")
        for notice in item.notices:
            st.warning(notice, icon=":material/health_and_safety:")
        st.markdown(theme.passage_html(item.passage), unsafe_allow_html=True)
        span = f"{format_time(item.start_s)} to {format_time(item.end_s)}"
        shown = "English translation" if item.view == "translation" else "Original words"
        st.caption(f"{shown} · {span}")
        listen_button(
            play, item.recording_id, f"listen-{item.evidence_id}", (item.start_s, item.end_s)
        )
        report_button(client, item.recording_id, item.evidence_id)


def _empty(spec: LibrarySpec) -> None:
    searched = "Nothing matched that search." if spec.q else "Nothing has been shared yet."
    st.markdown(
        f"<div class='hv-empty'><b>{searched}</b>Only recordings that an administrator has "
        "approved, and that their community has agreed to share with you, appear here.</div>",
        unsafe_allow_html=True,
    )


def search_and_show(
    client: ApiClient, fetch: Callable[[LibrarySpec], LibraryResult], play: Fetch
) -> None:
    """The search form and its results. `fetch` and `play` decide who is asking: a signed-in
    reader or an open visitor, so the same page serves both and the server applies the limits."""
    spec = _filters()
    try:
        items = fetch(spec).items
    except ApiError as error:
        st.error(message_for(error))
        return
    if not items:
        _empty(spec)
        return
    st.caption(f"{len(items)} shown")
    for item in items:
        _card(client, play, item)


def render(client: ApiClient) -> None:
    """The Library page for signed-in readers."""
    theme.page_header(
        "Library",
        "Songs, stories, lessons and living knowledge shared by communities. "
        "Choose a language, or search for what you want to find.",
        "library",
    )
    search_and_show(client, client.library, client.recording_media)
    theme.footer()
