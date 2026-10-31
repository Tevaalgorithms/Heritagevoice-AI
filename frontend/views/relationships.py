"""Relationships (admins): check what a model proposed from approved recordings.

Each proposal shows the words it came from. Approving it lets it reach the knowledge graph that
helps answer "how are these connected" questions; rejecting it keeps it out. A wrong name or link
can be corrected before approving. Nothing a model proposes is used until a person approves it.
"""

from html import escape

import streamlit as st

from frontend import theme
from frontend.api_client import ApiClient, ApiError, AssertionEditSpec, AssertionView
from frontend.format import format_time
from frontend.messages import message_for
from frontend.relations import RELATIONS, phrase

EMPTY = {
    "pending": "Nothing is waiting. Proposals appear here after a recording is published.",
    "approved": "No relationship has been approved yet.",
}


def _headline(item: AssertionView) -> str:
    return (
        f"<b>{escape(item.subject)}</b> {escape(phrase(item.relation))} "
        f"<b>{escape(item.object)}</b>"
    )


def _decide(
    client: ApiClient, item: AssertionView, approved: bool, edit: AssertionEditSpec | None = None
) -> None:
    try:
        client.decide_assertion(item.id, approved, edit)
    except ApiError as error:
        st.error(message_for(error))
        return
    st.rerun()


def _source(item: AssertionView) -> None:
    if item.passage:
        span = f"{format_time(item.start_s or 0)} to {format_time(item.end_s or 0)}"
        st.markdown(theme.passage_html(item.passage), unsafe_allow_html=True)
        st.caption(f"Said by {item.asserted_by} · {span} · confidence {item.confidence:.0%}")


def _correction(client: ApiClient, item: AssertionView) -> None:
    with st.expander("Correct it before approving"):
        with st.form(f"fix-{item.id}", border=False):
            subject = st.text_input("First name", item.subject)
            relation = st.selectbox(
                "Relationship",
                list(RELATIONS),
                index=list(RELATIONS).index(item.relation) if item.relation in RELATIONS else 0,
                format_func=phrase,
            )
            obj = st.text_input("Second name", item.object)
            saved = st.form_submit_button("Approve with these corrections")
        if saved:
            edit = AssertionEditSpec(subject=subject, relation=str(relation), object=obj)
            _decide(client, item, True, edit)


def _pending_card(client: ApiClient, item: AssertionView) -> None:
    with st.container(border=True):
        st.markdown(_headline(item), unsafe_allow_html=True)
        _source(item)
        approve, reject, _ = st.columns([1, 1, 3])
        if approve.button("Approve", type="primary", key=f"yes-{item.id}"):
            _decide(client, item, True)
        if reject.button("Reject", key=f"no-{item.id}"):
            _decide(client, item, False)
        _correction(client, item)


def _approved_card(client: ApiClient, item: AssertionView) -> None:
    with st.container(border=True):
        st.markdown(_headline(item), unsafe_allow_html=True)
        _source(item)
        if st.button("Withdraw", key=f"withdraw-{item.id}", help="Remove it from the graph."):
            _decide(client, item, False)


def _tab(client: ApiClient, state: str) -> None:
    try:
        items = client.assertions(state)
    except ApiError as error:
        st.error(message_for(error))
        return
    if not items:
        st.info(EMPTY[state])
        return
    st.caption(f"{len(items)} shown")
    card = _pending_card if state == "pending" else _approved_card
    for item in items:
        card(client, item)


def render(client: ApiClient) -> None:
    """The Relationships page."""
    theme.page_header(
        "Relationships",
        "Check the connections a model found between people, places, songs and customs.",
        "library",
    )
    pending, approved = st.tabs(
        [":material/pending_actions: To review", ":material/check: Approved"]
    )
    with pending:
        _tab(client, "pending")
    with approved:
        _tab(client, "approved")
