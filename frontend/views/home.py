"""The public home page: anyone can search the shared recordings; contributors sign in or sign up.

Searching needs no account. Adding recordings does: people create an account, an administrator
approves it, and then they sign in and upload. Administrators sign in the same way (their role
decides what they see) and are only ever added by another administrator.
"""

from collections.abc import Callable

import streamlit as st

from frontend import theme
from frontend.api_client import ApiClient
from frontend.views import library

SIGN_IN_LABEL = "Sign in"
CREATE_LABEL = "Create an account"
OPEN_NOTE = "Searching and reading what communities share is open to everyone."
STEPS = (
    ("Create an account", "Choose Sign up on the next page and confirm your email."),
    ("We approve it", "An administrator checks the request and links you to your group."),
    ("Add recordings", "Sign in, record or upload, and tell us what may be shared."),
)


def _steps_html() -> str:
    items = "".join(f"<li><b>{title}</b><span>{text}</span></li>" for title, text in STEPS)
    return f"<ol class='hv-steps'>{items}</ol>"


def _account_card(sign_in: Callable[[], None]) -> None:
    """Where contributors and administrators start. Everyone signs in the same secure way."""
    with st.container(border=True):
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


def render(client: ApiClient, sign_in: Callable[[], None]) -> None:
    """The landing page for visitors."""
    theme.landing_top()
    search, account = st.columns([5, 3], gap="large")
    with search:
        st.markdown("### Search the shared heritage")
        st.caption(OPEN_NOTE)
        library.search_and_show(client, client.public_library, client.public_recording_media)
    with account:
        _account_card(sign_in)
    theme.landing_details()
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
