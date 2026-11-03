"""The signed-in user: who they are and how they sign out."""

import streamlit as st

from app.config import Settings
from frontend.api_client import ApiClient, ApiError, ApiRequestError
from frontend.auth import cognito_enabled

FORBIDDEN = 403
UNAUTHORIZED = 401


class AwaitingApprovalError(Exception):
    """The sign-in worked, but no administrator has approved this account yet."""


class SessionExpiredError(Exception):
    """The API no longer accepts this sign-in (the access token has expired)."""


def current_role(client: ApiClient) -> str | None:
    """The signed-in user's role as the server sees it, or None if it cannot be read.

    Raises AwaitingApprovalError for a valid sign-in the server knows nothing about: someone who
    created their own account and has not been approved (or whose account was disabled).
    Raises SessionExpiredError when the sign-in itself is no longer valid."""
    try:
        return client.me().role
    except ApiRequestError as error:
        if error.status_code == FORBIDDEN:
            raise AwaitingApprovalError from error
        if error.status_code == UNAUTHORIZED:
            raise SessionExpiredError from error
        return None
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
