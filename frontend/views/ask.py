"""Ask page: a chat that talks to the API through the typed client."""

import streamlit as st

from frontend import theme
from frontend.api_client import ApiClient, ApiError
from frontend.messages import message_for

EXAMPLES = (
    "Who told the story of the harvest festival?",
    "What do the elders say about the old village well?",
    "Which songs were sung at weddings?",
)


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


def ask(client: ApiClient, question: str) -> None:
    st.session_state.messages.append({"role": "user", "content": question})
    st.session_state.messages.append({"role": "assistant", "content": answer_for(client, question)})
    st.rerun()


def suggestions(client: ApiClient) -> None:
    st.markdown(
        "<div class='hv-empty'><h3>What would you like to remember?</h3>"
        "<p class='hv-sub'>Ask about the stories, songs and traditions in the collection, "
        "or start with one of these.</p></div>",
        unsafe_allow_html=True,
    )
    for column, example in zip(st.columns(len(EXAMPLES)), EXAMPLES, strict=True):
        if column.button(example, use_container_width=True):
            ask(client, example)


def render(client: ApiClient) -> None:
    theme.page_header(
        "Ask", "Answers are drawn only from consented sources, with where they came from."
    )
    st.session_state.setdefault("messages", [])
    if st.session_state.messages and st.button("New conversation"):
        st.session_state.messages = []
        st.rerun()
    show_history()
    if not st.session_state.messages:
        suggestions(client)
    if question := st.chat_input("Ask about the stories in this collection"):
        ask(client, question)
    theme.footer()
