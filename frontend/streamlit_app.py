"""Shell with navigation (Upload, Review, Ask). The API token stays on the Streamlit server."""

import streamlit as st

from app.config import Settings
from frontend import theme
from frontend.account import current_role, show_account
from frontend.api_client import ApiClient, ApiError
from frontend.auth import COGNITO_PROVIDER, cognito_enabled, resolve_token
from frontend.messages import message_for
from frontend.views import ask, review, upload
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
    pages = [
        st.Page(
            lambda: upload.render(client),
            title="Upload",
            icon=":material/graphic_eq:",
            url_path="upload",
        ),
        st.Page(
            lambda: review.render(client),
            title="Review",
            icon=":material/fact_check:",
            url_path="review",
        ),
        st.Page(
            lambda: ask.render(client),
            title="Ask",
            icon=":material/forum:",
            url_path="ask",
            default=True,
        ),
    ]
    if role == "admin":
        pages.append(
            st.Page(
                lambda: settings_page.render(client),
                title="Settings",
                icon=":material/tune:",
                url_path="settings",
            )
        )
    st.navigation(pages).run()


main()
