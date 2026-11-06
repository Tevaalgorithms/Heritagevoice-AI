"""The public home page: what HeritageVoice is, how it works, what it stands for, and what has
been shared. Anyone can read and listen; people who want to add recordings sign in or sign up.

Adding recordings needs an account: people create one, an administrator approves it, and then they
sign in and upload. Administrators sign in the same way (their role decides what they see) and are
only ever added by another administrator.
"""

from collections.abc import Callable

import streamlit as st

from frontend import theme
from frontend.api_client import ApiClient, ApiError
from frontend.api_models import LibrarySpec
from frontend.views import library

RECENT = 3
TRUST = ("Shared with consent", "Reviewed by a person", "Credited when the speaker agrees")
CHECK = (
    "<svg viewBox='0 0 24 24' width='18' height='18' fill='none' stroke='#B4532A' "
    "stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'><path d='M20 6 9 17l-5-5'/>"
    "</svg>"
)
HOW = (
    (
        "Record in your own language",
        "Speak a song, story, lesson or practice, or upload a file. What the group allows is "
        "recorded first.",
    ),
    (
        "People review it",
        "AI writes it down and translates it. A person checks every transcript, translation and "
        "connection before anyone can search it.",
    ),
    (
        "Ask, and hear the source",
        "Answers use the recordings only. Each one cites the moment it came from, and you can "
        "listen to it.",
    ),
)
PRINCIPLES = (
    (
        "Consent first",
        "Nothing is processed or shared until the speaker's consent is recorded. "
        "It can be withdrawn at any time.",
    ),
    ("People decide", "AI drafts. People review. Only approved material becomes searchable."),
    (
        "Answers with sources",
        "If the recordings do not say, the answer says so. It never invents a remedy or a history.",
    ),
    (
        "Community in control",
        "Families and groups choose who may hear what, and can change their mind later.",
    ),
)


def _trust_html() -> str:
    """The product's three promises as a short line of checks, fixed text."""
    items = "".join(f"<li>{CHECK}<span>{text}</span></li>" for text in TRUST)
    return f"<ul class='hv-trust'>{items}</ul>"


def _section(title: str, text: str) -> None:
    st.markdown(
        f"<div class='hv-section'><h2>{title}</h2><p>{text}</p></div>", unsafe_allow_html=True
    )


def _search_card(library_page: object) -> None:
    """Search from the Home page: the Library opens with these words and choices filled in."""
    with st.form("home-search", border=False):
        st.markdown("#### Search the shared heritage")
        words = st.text_input(
            "Search by words, in any language",
            placeholder="For example: harvest, grandmother, humility",
        )
        left, right = st.columns(2)
        language = left.selectbox("Language spoken", list(library.language_options()))
        kind = right.selectbox("Kind", list(library.kind_options()))
        go = st.form_submit_button("Search", type="primary", use_container_width=True)
        st.caption("Reading and listening to what communities share openly needs no account.")
    if go:
        st.session_state[library.PENDING] = (words.strip(), language, kind)
        st.switch_page(library_page)  # type: ignore[arg-type]


def _intro(sign_in: Callable[[], None], library_page: object) -> None:
    left, right = st.columns([5, 4], gap="large")
    with left:
        st.markdown(
            "<div class='hv-title'>Every elder's voice is a library.</div>"
            "<p class='hv-lede'>We help communities keep their songs, stories, lessons and living "
            "knowledge alive, in their own voices and with their consent.</p>",
            unsafe_allow_html=True,
        )
        browse, share, _ = st.columns([4, 4, 2])
        if browse.button("Browse the Library", type="primary", icon=":material/menu_book:"):
            st.switch_page(library_page)  # type: ignore[arg-type]
        share.button("Share a recording", icon=":material/mic:", on_click=sign_in)
        st.markdown(_trust_html(), unsafe_allow_html=True)
    with right:
        _search_card(library_page)


def _recent(client: ApiClient, library_page: object) -> None:
    """The newest recordings shared openly, with the Library's listen and report buttons."""
    _section("Recently shared", "Open to everyone. Each recording shows when it was added.")
    try:
        items = client.public_library(LibrarySpec(limit=RECENT)).items
    except ApiError:
        items = []
    if not items:
        st.info("Recordings appear here once communities share them openly.")
    for column, item in zip(st.columns(RECENT), items, strict=False):
        with column:
            library.card(client, client.public_recording_media, item)
    st.page_link(
        library_page, label="See everything in the Library", icon=":material/arrow_forward:"
    )  # type: ignore[arg-type]


def render(client: ApiClient, sign_in: Callable[[], None], library_page: object) -> None:
    """The landing page for visitors."""
    st.image(str(theme.BANNER), use_container_width=True)
    _intro(sign_in, library_page)
    with theme.band("how"):
        _section("How it works", "From a voice to an answer you can trace back to who said it.")
        st.markdown(theme.cards_html(HOW, 3, "steps"), unsafe_allow_html=True)
    _section("What we hold to", "The rules the product is built around.")
    st.markdown(theme.cards_html(PRINCIPLES, 4, "principles"), unsafe_allow_html=True)
    with theme.band("recent"):
        _recent(client, library_page)
    theme.kinds()
    theme.languages_band()
    theme.footer(languages=False)


def render_expired(sign_out: Callable[[], None]) -> None:
    """Shown when the sign-in has expired: say so, and clear it so signing in starts afresh."""
    theme.page_header(
        "Your sign-in has expired",
        "For your safety you are signed out after a while. Nothing you saved is lost. "
        "Press the button, then choose Sign in.",
        "people",
    )
    st.button("Continue", type="primary", icon=":material/login:", on_click=sign_out)


def render_waiting() -> None:
    """Shown to someone who is signed in but not yet approved."""
    theme.page_header(
        "Your account is waiting for approval",
        "Thank you for signing up. An administrator reviews each new account and links it to a "
        "group before it can add recordings.",
        "people",
    )
    st.markdown(
        "You do not need to do anything else. Once you are approved, sign in again and "
        "**Add a recording** will be there. Meanwhile you can read what communities have shared "
        "from the Home page after signing out."
    )
    st.caption("Waiting a long time? Use the contact address on the Contact and takedown page.")
