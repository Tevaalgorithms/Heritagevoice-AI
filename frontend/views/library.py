"""Library page: browse or search what you may read, in the language you choose.

Everything listed has been approved by an admin and shared by its community. The server decides
what each person may see; this page only asks and displays. Remedies arrive with a notice that
is always shown next to the passage.
"""

from collections.abc import Callable
from html import escape

import streamlit as st

from app.languages import BY_CODE, LANGUAGES
from app.models.groups import OPEN_COMMUNITY
from frontend import theme
from frontend.api_client import ApiClient, ApiError, LibraryItem, LibraryResult, LibrarySpec
from frontend.credit import origin_line
from frontend.format import format_time
from frontend.kinds import KINDS, label_for
from frontend.messages import message_for
from frontend.views.playback import Fetch, listen_button
from frontend.views.report import report_button

ANY = "Any"
PENDING = "hv-pending-search"  # what the Home page search card asked for
VIEWS = {"Original": "original", "English": "translation"}


def language_options() -> dict[str, str]:
    options = {ANY: ""}
    options.update({f"{lang.name} · {lang.native_name}": lang.code for lang in LANGUAGES})
    return options


def kind_options() -> dict[str, str]:
    options = {ANY: ""}
    options.update({f"{kind.icon} {kind.label}": kind.key for kind in KINDS})
    return options


def _take_pending() -> None:
    """Fill the filters with the search made on the Home page, once."""
    pending = st.session_state.pop(PENDING, None)
    if pending:
        st.session_state.update(zip(("lib-q", "lib-language", "lib-kind"), pending, strict=True))


def _filters() -> LibrarySpec:
    """The search box and the choices that narrow it."""
    _take_pending()
    with st.form("library-search", border=False):
        query = st.text_input(
            "Search",
            placeholder="Search by words, in any language",
            label_visibility="collapsed",
            key="lib-q",
        )
        languages, kinds, view = st.columns(3)
        language = languages.selectbox(
            "Language spoken", list(language_options()), key="lib-language"
        )
        kind = kinds.selectbox("Kind", list(kind_options()), key="lib-kind")
        read_as = view.segmented_control("Read in", list(VIEWS), default=next(iter(VIEWS)))
        st.form_submit_button("Search", icon=":material/search:", type="primary")
    return LibrarySpec(
        q=query.strip(),
        language=language_options()[str(language)],
        kind=kind_options()[str(kind)],
        view=VIEWS.get(str(read_as), "original"),
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


def _origin(item: LibraryItem) -> str:
    """When it was added and, if the consent allows, who to thank and where it came from."""
    credit = item.credit
    return origin_line(
        item.added,
        credit.name if credit else None,
        credit.source_kind if credit else None,
        credit.source_note if credit else None,
    )


def card(client: ApiClient, play: Fetch, item: LibraryItem) -> None:
    with theme.card(item.evidence_id):
        st.markdown(f"<div class='hv-kind'>{escape(_heading(item))}</div>", unsafe_allow_html=True)
        for notice in item.notices:
            st.warning(notice, icon=":material/health_and_safety:")
        st.markdown(theme.passage_html(item.passage), unsafe_allow_html=True)
        span = f"{format_time(item.start_s)} to {format_time(item.end_s)}"
        shown = "English translation" if item.view == "translation" else "Original words"
        st.caption(f"{shown} · {span}")
        origin = _origin(item)
        if origin:
            st.caption(origin)
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
        card(client, play, item)


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


def render_public(client: ApiClient) -> None:
    """The Library page for visitors: only what communities shared openly, no account needed."""
    theme.page_header(
        "Library",
        "Songs, stories, lessons and living knowledge shared openly by communities. "
        "Choose a language, or search for what you want to find.",
        "library",
    )
    search_and_show(client, client.public_library, client.public_recording_media)
    theme.footer()
