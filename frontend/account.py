"""The signed-in user: who they are and how they sign out."""

import streamlit as st

from app.config import Settings
from frontend.api_client import ApiClient, ApiError
from frontend.auth import cognito_enabled


def current_role(client: ApiClient) -> str | None:
    """The signed-in user's role as the server sees it, or None if it cannot be read."""
    try:
        return client.me().role
    except ApiError:
        return None


def show_account(role: str | None, settings: Settings) -> None:
    """Who is signed in, with a sign-out button when signing in goes through Cognito."""
    if role:
        st.sidebar.caption(f"Signed in as **{role}**")
    if cognito_enabled(settings) and st.user.is_logged_in:
        st.sidebar.button(
            "Sign out", icon=":material/logout:", on_click=st.logout, key="hv-sign-out"
        )
