"""API-backed shell. API token stays on the Streamlit server, not in browser inputs."""

from http import HTTPStatus

import httpx
import streamlit as st

from app.config import Settings

st.set_page_config(page_title="HeritageVoice AI", page_icon="📚")
st.title("HeritageVoice AI")
st.caption("Development scaffold — retrieval and answer integrations are pending.")
settings = Settings()
if "messages" not in st.session_state:
    st.session_state.messages = []
if st.button("New chat"):
    st.session_state.messages = []
    st.rerun()
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])
if question := st.chat_input("Ask about heritage sources"):
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.write(question)
    token = settings.dev_api_token
    if token is None or not token.get_secret_value():
        response_text = "Configure local development access in .env to contact the API."
    else:
        try:
            with st.spinner("Contacting HeritageVoice…"):
                response = httpx.post(
                    f"{settings.api_url.rstrip('/')}/query",
                    headers={"Authorization": f"Bearer {token.get_secret_value()}"},
                    json={"question": question},
                    timeout=50,
                )
                response.raise_for_status()
                response_text = response.json().get("answer", "No answer returned.")
        except httpx.HTTPStatusError as error:
            if error.response.status_code == HTTPStatus.SERVICE_UNAVAILABLE:
                response_text = "The agent integrations are not ready yet."
            else:
                response_text = (
                    f"The request could not be completed ({error.response.status_code})."
                )
        except httpx.RequestError:
            response_text = "The API is unavailable. Start it using the README instructions."
    st.session_state.messages.append({"role": "assistant", "content": response_text})
    with st.chat_message("assistant"):
        st.write(response_text)
