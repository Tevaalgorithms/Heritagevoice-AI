"""The public home page: anyone can search the shared recordings; contributors sign in here too.

Searching needs no account. Uploading, asking questions and the admin portal do. The sign-in box
sits beside the search so a contributor or administrator finds it at once, while a visitor who only
wants to read is never made to sign in.
"""

from collections.abc import Callable

import streamlit as st

from frontend import theme
from frontend.api_client import ApiClient
from frontend.views import library

SIGN_IN_LABEL = "Sign in or create an account"
ACCOUNT_NOTE = (
    "Accounts are for people who contribute recordings and for administrators. "
    "Searching and reading what communities have shared publicly is open to everyone."
)


def _account_card(sign_in: Callable[[], None]) -> None:
    """Where contributors and administrators start."""
    with st.container(border=True):
        st.markdown("#### Contribute or manage")
        st.caption(ACCOUNT_NOTE)
        st.button(
            SIGN_IN_LABEL,
            icon=":material/login:",
            type="primary",
            use_container_width=True,
            on_click=sign_in,
            key="hv-sign-in",
        )
        st.caption(
            "Sign-in uses a password and a second step. New accounts are approved by an "
            "administrator before they can add recordings."
        )


def render(client: ApiClient, sign_in: Callable[[], None]) -> None:
    """The landing page for visitors."""
    theme.landing_top()
    search, account = st.columns([3, 1.4], gap="large")
    with search:
        st.markdown("### Search the shared heritage")
        library.search_and_show(client.public_library)
    with account:
        _account_card(sign_in)
    theme.landing_details()
    theme.footer()
