"""Ask page: a chat that talks to the API through the typed client."""

import streamlit as st

from frontend import theme
from frontend.api_client import ApiClient, ApiError, CitationView, QueryResult
from frontend.format import format_time
from frontend.messages import message_for
from frontend.views.report import report_button

NO_ANSWER = "No answer was returned."
STATUS_NOTES = {
    "partial": "This answers only part of your question. Check the sources below.",
    "insufficient_evidence": "Nothing in the recordings you can read answers this.",
}
EXAMPLES = (
    "Which songs were sung during the harvest?",
    "What lessons did the grandparents pass down?",
    "How was the land prepared before planting?",
)


def answer_for(client: ApiClient, question: str) -> dict[str, object]:
    """One assistant turn: the text, and the sources when the answer has them."""
    try:
        with st.spinner("Looking through the recordings…"):
            result = client.query(question)
    except ApiError as error:
        return {"role": "assistant", "content": message_for(error), "result": None}
    return {"role": "assistant", "content": result.answer or NO_ANSWER, "result": result}


def _listen(client: ApiClient, citation: CitationView, key: str) -> None:
    """Play the cited moment. Fails quietly when the recording is not playable for this reader."""
    if not st.button("Listen", icon=":material/play_circle:", key=key):
        return
    try:
        audio, kind = client.recording_media(citation.recording_id)
    except ApiError:
        st.caption("This recording cannot be played here.")
        return
    st.audio(audio, format=kind, start_time=int(citation.start_s), end_time=int(citation.end_s))


def _source(client: ApiClient, number: int, citation: CitationView, scope: str) -> None:
    span = f"{format_time(citation.start_s)} to {format_time(citation.end_s)}"
    st.markdown(f"**[{number}]** {citation.title} · {span}")
    for notice in citation.notices:
        st.warning(notice, icon=":material/health_and_safety:")
    st.markdown(theme.passage_html(citation.passage), unsafe_allow_html=True)
    _listen(client, citation, f"listen-{scope}-{number}")
    report_button(client, citation.recording_id, f"{scope}-{number}")


def _sources(client: ApiClient, result: QueryResult, scope: str) -> None:
    if not result.citations:
        return
    with st.expander(f"Sources ({len(result.citations)})"):
        for number, citation in enumerate(result.citations, start=1):
            _source(client, number, citation, scope)


def _status_note(result: QueryResult) -> None:
    note = STATUS_NOTES.get(result.status)
    if note:
        st.info(note, icon=":material/info:")


def show_history(client: ApiClient) -> None:
    for index, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(theme.answer_html(message["content"]), unsafe_allow_html=True)
            result = message.get("result")
            if result is not None:
                _status_note(result)
                _sources(client, result, str(index))


def ask(client: ApiClient, question: str) -> None:
    st.session_state.messages.append({"role": "user", "content": question, "result": None})
    st.session_state.messages.append(answer_for(client, question))
    st.rerun()


def suggestions(client: ApiClient) -> None:
    st.markdown(
        "<div class='hv-empty'><h3>What would you like to remember?</h3>"
        "<p class='hv-sub'>Ask about the songs, stories, lessons and practices in the "
        "collection, or start with one of these.</p></div>",
        unsafe_allow_html=True,
    )
    for column, example in zip(st.columns(len(EXAMPLES)), EXAMPLES, strict=True):
        if column.button(example, use_container_width=True):
            ask(client, example)


def render(client: ApiClient) -> None:
    theme.page_header(
        "Ask",
        "Answers are drawn only from consented sources, with where they came from.",
        "ask",
    )
    st.session_state.setdefault("messages", [])
    if st.session_state.messages and st.button("New conversation"):
        st.session_state.messages = []
        st.rerun()
    show_history(client)
    if not st.session_state.messages:
        suggestions(client)
    if question := st.chat_input("Ask about the songs, stories and knowledge in this collection"):
        ask(client, question)
    theme.footer()
