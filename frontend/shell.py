"""The frame around every page: the logo, the account buttons at the top right, and the footer
with the legal links. The menu itself is Streamlit's top navigation (see `streamlit_app.py`)."""

from collections.abc import Callable
from pathlib import Path

import streamlit as st

from frontend.legal import OrganisationFacts
from frontend.roles import role_label

LOGO = Path(__file__).parent / "static" / "logo.svg"


def logo() -> None:
    """The wordmark at the top left of the header."""
    st.logo(str(LOGO), size="large")


def visitor_account(sign_in: Callable[[], None]) -> None:
    """Create account and Sign in, at the top right. Both go to the same secure sign-in page, which
    has a Sign up link for new people."""
    with st.container(key="hv-account"):
        st.button("Create account", key="hv-header-create", on_click=sign_in)
        st.button("Sign in", key="hv-header-signin", type="primary", on_click=sign_in)


def member_account(role: str | None, can_sign_out: bool) -> None:
    """Who is signed in and how to sign out, at the top right. Local development, which signs in
    with a token instead of Cognito, has nothing to sign out of."""
    with st.container(key="hv-account"):
        if role:
            st.markdown(f"<span class='hv-who'>{role_label(role)}</span>", unsafe_allow_html=True)
        if can_sign_out:
            st.button("Sign out", key="hv-sign-out", on_click=st.logout, icon=":material/logout:")


def footer(legal: list[object], facts: OrganisationFacts) -> None:
    """The legal links and the operator's name, under every page."""
    with st.container(key="hv-footer"):
        st.divider()
        links = st.columns([1.2, *[1] * len(legal)], gap="small")
        links[0].markdown(
            f"<span class='hv-foot'>&copy; {facts.operator}</span>", unsafe_allow_html=True
        )
        for column, page in zip(links[1:], legal, strict=True):
            with column:
                st.page_link(page)  # type: ignore[arg-type]
