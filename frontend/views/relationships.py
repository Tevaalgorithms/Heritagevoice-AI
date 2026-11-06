"""Relationships (admins): check what a model proposed from approved recordings.

Each proposal shows the words it came from. Approving it lets it reach the knowledge graph that
helps answer "how are these connected" questions; rejecting it keeps it out. A wrong name or link
can be corrected before approving. Nothing a model proposes is used until a person approves it.
"""

from html import escape

import streamlit as st

from frontend import theme
from frontend.api_client import (
    ApiClient,
    ApiError,
    AssertionEditSpec,
    AssertionView,
    VoiceSuggestionView,
)
from frontend.format import format_time
from frontend.messages import message_for
from frontend.relations import RELATIONS, headline_html, phrase
from frontend.spoken import LANGUAGE_CHOICES

LESSONS = ("தவறு", "பணிவு", "முயற்சி", "ஒற்றுமை", "நன்றி")  # short lesson words, in Tamil
NAME_HELP = (
    "Write it in the language of the recording, as the speaker said it. "
    "Short, general words link best across recordings."
)
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


def _voice_key(item: AssertionView) -> str:
    return f"voice-{item.id}"


def _understand(client: ApiClient, item: AssertionView, language: str, audio: bytes) -> None:
    try:
        with st.spinner("Listening and understanding… this can take up to a minute."):
            suggestion = client.voice_correction(item.id, audio, language)
    except ApiError as error:
        st.error(message_for(error))
        return
    st.session_state[_voice_key(item)] = suggestion


def _show_heard(suggestion: VoiceSuggestionView) -> None:
    st.markdown("**What I heard**")
    st.text(suggestion.heard or "(nothing could be heard)")
    if suggestion.english and suggestion.english != suggestion.heard:
        st.caption(f"In English: {suggestion.english}")
    if not suggestion.understood:
        st.warning("I could not tell what to change. Record it again, or type it below.")


def _voice(client: ApiClient, item: AssertionView) -> VoiceSuggestionView | None:
    """Record a correction in your own language; returns what was understood, if anything."""
    st.markdown("**Speak your correction**")
    st.caption(
        "Say in your own language what is wrong and what it should be. The recording is deleted "
        "as soon as it has been understood. You check the result before anything is saved."
    )
    label = st.selectbox("Language you will speak", list(LANGUAGE_CHOICES), key=f"vl-{item.id}")
    recorded = st.audio_input("Record", label_visibility="collapsed", key=f"va-{item.id}")
    asked = st.button("Understand my correction", key=f"vb-{item.id}", disabled=recorded is None)
    if asked and recorded is not None:
        _understand(client, item, LANGUAGE_CHOICES[str(label)], recorded.getvalue())
    suggestion: VoiceSuggestionView | None = st.session_state.get(_voice_key(item))
    if suggestion is not None:
        _show_heard(suggestion)
    return suggestion


def _starting_point(item: AssertionView, suggestion: VoiceSuggestionView | None) -> AssertionView:
    """What the typed form starts from: the spoken correction if it was understood."""
    if suggestion is None or not suggestion.understood or suggestion.relation is None:
        return item
    return item.model_copy(
        update={
            "subject": suggestion.subject,
            "relation": suggestion.relation,
            "object": suggestion.object,
        }
    )


def _copy_pick(key: str) -> None:
    """Put the name chosen from the chips into the text box."""
    picked = st.session_state.get(f"{key}-pick")
    if picked:
        st.session_state[key] = picked


def _name_field(label: str, key: str, start: str, suggestions: tuple[str, ...]) -> str:
    """A name box, with clickable names to reuse so the spelling stays the same."""
    box = f"{key}-{abs(hash(start))}"  # a new start (a spoken correction) gives a fresh box
    value = st.text_input(label, start, key=box, help=NAME_HELP)
    if suggestions:
        st.pills(
            "Use one that is already there",
            suggestions,
            key=f"{box}-pick",
            on_change=_copy_pick,
            args=(box,),
        )
    return value


def _correction_form(
    client: ApiClient, item: AssertionView, start: AssertionView, names: tuple[str, ...]
) -> None:
    """From, the relationship, and To: any two things (a saying, a person, a place, an idea)."""
    subject = _name_field("From", f"from-{item.id}", start.subject, names)
    relation = str(
        st.selectbox(
            "Relationship",
            list(RELATIONS),
            index=list(RELATIONS).index(start.relation) if start.relation in RELATIONS else 0,
            format_func=phrase,
            key=f"rel-{item.id}",
        )
    )
    lessons = LESSONS if relation == "TEACHES" else names
    obj = _name_field("To", f"to-{item.id}", start.object, lessons)
    st.markdown(
        f"<div class='hv-sentence'>{headline_html(subject, relation, obj)}</div>",
        unsafe_allow_html=True,
    )
    if st.button("Approve with these corrections", key=f"fixok-{item.id}"):
        _decide(
            client, item, True, AssertionEditSpec(subject=subject, relation=relation, object=obj)
        )


def _modify(client: ApiClient, item: AssertionView, names: tuple[str, ...]) -> None:
    """Modify: speak the correction in your own language, or type it. A person approves it."""
    with st.expander("Modify: speak or type a correction"):
        suggestion = _voice(client, item)
        st.markdown("**Check and approve**")
        _correction_form(client, item, _starting_point(item, suggestion), names)


def _pending_card(client: ApiClient, item: AssertionView, names: tuple[str, ...]) -> None:
    with theme.card(f"pending-{item.id}"):
        st.markdown(_headline(item), unsafe_allow_html=True)
        _source(item)
        approve, reject, _ = st.columns([1, 1, 3])
        if approve.button("Approve", type="primary", key=f"yes-{item.id}"):
            _decide(client, item, True)
        if reject.button("Reject", key=f"no-{item.id}"):
            _decide(client, item, False)
        _modify(client, item, names)


def _approved_card(client: ApiClient, item: AssertionView) -> None:
    with theme.card(f"approved-{item.id}"):
        st.markdown(_headline(item), unsafe_allow_html=True)
        _source(item)
        if st.button("Withdraw", key=f"withdraw-{item.id}", help="Remove it from the graph."):
            _decide(client, item, False)


def _known_names(client: ApiClient) -> tuple[str, ...]:
    """Names already in approved relationships, to reuse so the spelling stays the same."""
    try:
        approved = client.assertions("approved")
    except ApiError:
        return ()
    return tuple(sorted({n for item in approved for n in (item.subject, item.object)}))


def _cards(client: ApiClient, state: str, items: list[AssertionView]) -> None:
    if state != "pending":
        for item in items:
            _approved_card(client, item)
        return
    names = _known_names(client)
    for item in items:
        _pending_card(client, item, names)


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
    _cards(client, state, items)


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
