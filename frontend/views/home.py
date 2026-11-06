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

SIGN_IN_LABEL = "Sign in"
CREATE_LABEL = "Create an account"
RECENT = 3
STEPS = (
    ("Create an account", "Choose Sign up on the next page and confirm your email."),
    ("We approve it", "An administrator checks the request and links you to your group."),
    ("Add recordings", "Sign in, record or upload, and tell us what may be shared."),
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


def _section(title: str, text: str) -> None:
    st.markdown(
        f"<div class='hv-section'><h2>{title}</h2><p>{text}</p></div>", unsafe_allow_html=True
    )


def _steps_html() -> str:
    items = "".join(f"<li><b>{title}</b><span>{text}</span></li>" for title, text in STEPS)
    return f"<ol class='hv-steps'>{items}</ol>"


def _account_card(sign_in: Callable[[], None]) -> None:
    """Where contributors and administrators start. Everyone signs in the same secure way."""
    with theme.card("share"):
        st.markdown("#### Share your heritage")
        st.markdown(_steps_html(), unsafe_allow_html=True)
        st.button(
            SIGN_IN_LABEL,
            icon=":material/login:",
            type="primary",
            use_container_width=True,
            on_click=sign_in,
            key="hv-sign-in",
        )
        st.button(
            CREATE_LABEL,
            icon=":material/person_add:",
            use_container_width=True,
            on_click=sign_in,
            key="hv-create-account",
        )


def _intro(sign_in: Callable[[], None], library_page: object) -> None:
    left, right = st.columns([5, 3], gap="large")
    with left:
        st.markdown(
            "<div class='hv-title'>Every elder's voice is a library.</div>"
            "<p class='hv-lede'>We help communities keep their songs, stories, lessons and living "
            "knowledge alive, in their own voices and with their consent.</p>",
            unsafe_allow_html=True,
        )
        browse, share = st.columns(2)
        if browse.button("Browse the Library", type="primary", icon=":material/menu_book:"):
            st.switch_page(library_page)  # type: ignore[arg-type]
        share.button("Share a recording", icon=":material/mic:", on_click=sign_in)
    with right:
        _account_card(sign_in)


def _recent(client: ApiClient, library_page: object) -> None:
    """The newest recordings shared openly, with the Library's listen and report buttons."""
    _section("Recently shared", "Open to everyone. Each recording shows when it was added.")
    try:
        items = client.public_library(LibrarySpec(limit=RECENT)).items
    except ApiError:
        items = []
    if not items:
        st.info("Recordings appear here once communities share them openly.")
    for item in items:
        library.card(client, client.public_recording_media, item)
    st.page_link(
        library_page, label="See everything in the Library", icon=":material/arrow_forward:"
    )  # type: ignore[arg-type]


def render(client: ApiClient, sign_in: Callable[[], None], library_page: object) -> None:
    """The landing page for visitors."""
    st.image(str(theme.BANNER), use_container_width=True)
    _intro(sign_in, library_page)
    _section("How it works", "From a voice to an answer you can trace back to who said it.")
    st.markdown(theme.cards_html(HOW, 3), unsafe_allow_html=True)
    _section("What we hold to", "The rules the product is built around.")
    st.markdown(theme.cards_html(PRINCIPLES, 4), unsafe_allow_html=True)
    _recent(client, library_page)
    theme.kinds_and_languages()
    theme.footer()


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
