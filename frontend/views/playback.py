"""Play a recording from a page. One button, one place, so every page behaves the same way."""

from collections.abc import Callable

import streamlit as st

from frontend.api_client import ApiError

Fetch = Callable[[str], tuple[bytes, str]]


def listen_button(
    fetch: Fetch, recording_id: str, key: str, span: tuple[float, float] | None = None
) -> None:
    """A Listen button. The audio is fetched only when pressed, and a recording that cannot be
    played (private, withdrawn, taken down) is reported quietly. `span` is the cited moment."""
    if not st.button("Listen", icon=":material/play_circle:", key=key):
        return
    try:
        audio, kind = fetch(recording_id)
    except ApiError:
        st.caption("This recording cannot be played here.")
        return
    if span is None:
        st.audio(audio, format=kind)
    else:
        st.audio(audio, format=kind, start_time=int(span[0]), end_time=int(span[1]))
