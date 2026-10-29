"""Shell with navigation (Upload, Review, Ask). The API token stays on the Streamlit server."""

import streamlit as st

from app.config import Settings
from frontend.api_client import ApiClient, ApiError
from frontend.messages import message_for
from frontend.views import ask, review, upload

st.set_page_config(page_title="HeritageVoice AI", page_icon="📚")


def make_client() -> ApiClient:
    settings = Settings()
    token = settings.dev_api_token.get_secret_value() if settings.dev_api_token else None
    return ApiClient(settings.api_url, token)


def show_status(client: ApiClient) -> None:
    try:
        report = client.ready()
    except ApiError as error:
        st.sidebar.error(message_for(error))
        return
    label = "API ready" if report.ready else "API running, dependencies not ready"
    (st.sidebar.success if report.ready else st.sidebar.warning)(label)


def main() -> None:
    client = make_client()
    st.sidebar.title("HeritageVoice AI")
    show_status(client)
    pages = [
        st.Page(upload.render, title="Upload", icon="🎙️", url_path="upload"),
        st.Page(review.render, title="Review", icon="✅", url_path="review"),
        st.Page(lambda: ask.render(client), title="Ask", icon="💬", url_path="ask", default=True),
    ]
    st.navigation(pages).run()


main()
