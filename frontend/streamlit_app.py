"""Shell with navigation by role. The API token stays on the Streamlit server."""

from collections.abc import Callable

import streamlit as st

from app.config import Settings
from frontend import theme
from frontend.account import current_role, show_account
from frontend.api_client import ApiClient, ApiError
from frontend.auth import COGNITO_PROVIDER, cognito_enabled, resolve_token
from frontend.messages import message_for
from frontend.views import ask, library, review, upload
from frontend.views import settings as settings_page

st.set_page_config(page_title="HeritageVoice AI", page_icon="🪔", layout="wide")


def require_sign_in(settings: Settings, token: str | None) -> None:
    """Without a token and with Cognito configured, offer sign-in and stop rendering."""
    if token is None and cognito_enabled(settings):
        theme.landing_top()
        theme.sign_in_button(lambda: st.login(COGNITO_PROVIDER))
        theme.landing_details()
        theme.footer()
        st.stop()


def show_status(client: ApiClient) -> None:
    try:
        report = client.ready()
    except ApiError as error:
        st.sidebar.error(message_for(error))
        return
    label = "API ready" if report.ready else "API running, dependencies not ready"
    (st.sidebar.success if report.ready else st.sidebar.warning)(label)


def _page(render: Callable[[ApiClient], None], client: ApiClient, **options: object) -> object:
    return st.Page(lambda: render(client), **options)  # type: ignore[arg-type]


def _pages(client: ApiClient, role: str | None) -> list[object]:
    """Everyone reads the Library and can add a recording; reviewing and settings are admin-only."""
    pages = [
        _page(
            library.render,
            client,
            title="Library",
            icon=":material/menu_book:",
            url_path="library",
            default=True,
        ),
        _page(ask.render, client, title="Ask", icon=":material/forum:", url_path="ask"),
        _page(
            upload.render, client, title="Add a recording", icon=":material/mic:", url_path="upload"
        ),
    ]
    if role == "admin":
        pages.append(
            _page(
                review.render,
                client,
                title="Review",
                icon=":material/fact_check:",
                url_path="review",
            )
        )
        pages.append(
            _page(
                settings_page.render,
                client,
                title="Settings",
                icon=":material/tune:",
                url_path="settings",
            )
        )
    return pages


def main() -> None:
    theme.apply()
    settings = Settings()
    token = resolve_token(settings, st.user)
    require_sign_in(settings, token)
    client = ApiClient(settings.api_url, token)
    theme.brand()
    show_status(client)
    role = current_role(client)
    show_account(role, settings)
    st.navigation(_pages(client, role)).run()


main()
