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

SIGN_IN_LABEL = "Contributor sign in"
ADMIN_LABEL = "Administrator sign in"
ACCOUNT_NOTE = (
    "Sign in to add recordings. Searching and reading what communities have shared publicly "
    "is open to everyone and needs no account."
)
ADMIN_NOTE = "Administrators review recordings and manage settings."
INVITE_NOTE = (
    "New contributor accounts are created by an administrator. "
    "Ask yours to invite you, then sign in with the email they used."
)


def _account_card(sign_in: Callable[[], None]) -> None:
    """Where contributors and administrators start. Both use the same secure sign-in; the
    account's role decides which sections they see afterwards."""
    with st.container(border=True):
        st.markdown("#### Contribute or manage")
        st.caption(ACCOUNT_NOTE)
        st.button(
            SIGN_IN_LABEL,
            icon=":material/mic:",
            type="primary",
            use_container_width=True,
            on_click=sign_in,
            key="hv-sign-in",
        )
        st.caption(ADMIN_NOTE)
        st.button(
            ADMIN_LABEL,
            icon=":material/admin_panel_settings:",
            use_container_width=True,
            on_click=sign_in,
            key="hv-admin-sign-in",
        )
        st.caption(INVITE_NOTE)


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
