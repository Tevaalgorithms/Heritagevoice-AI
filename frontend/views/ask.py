"""Ask page: a chat that talks to the API through the typed client."""

import streamlit as st

from frontend.api_client import ApiClient, ApiError
from frontend.messages import message_for


def answer_for(client: ApiClient, question: str) -> str:
    try:
        with st.spinner("Contacting HeritageVoice…"):
            return client.query(question).answer or "No answer returned."
    except ApiError as error:
        return message_for(error)


def show_history() -> None:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])


def render(client: ApiClient) -> None:
    st.header("Ask")
    st.session_state.setdefault("messages", [])
    if st.button("New chat"):
        st.session_state.messages = []
        st.rerun()
    show_history()
    if question := st.chat_input("Ask about heritage sources"):
        st.session_state.messages.append({"role": "user", "content": question})
        st.session_state.messages.append(
            {"role": "assistant", "content": answer_for(client, question)}
        )
        st.rerun()
