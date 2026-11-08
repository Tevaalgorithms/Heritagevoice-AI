"""Play a recording from a page. One button, one place, so every page behaves the same way."""

from collections.abc import Callable
from typing import NamedTuple

import streamlit as st

from frontend.api_client import ApiError

Fetch = Callable[[str], tuple[bytes, str]]


class Moment(NamedTuple):
    """The cited part of a recording, and what to say under the player (for example that the
    voice is synthetic)."""

    start_s: float
    end_s: float
    note: str | None = None


def listen_button(fetch: Fetch, recording_id: str, key: str, moment: Moment | None = None) -> None:
    """A Listen button. The audio is fetched only when pressed, and a recording that cannot be
    played (private, withdrawn, taken down) is reported quietly. `moment` is the cited part."""
    if not st.button("Listen", icon=":material/play_circle:", key=key):
        return
    try:
        audio, kind = fetch(recording_id)
    except ApiError:
        st.caption("This recording cannot be played here.")
        return
    if moment is None:
        st.audio(audio, format=kind)
        return
    st.audio(audio, format=kind, start_time=int(moment.start_s), end_time=int(moment.end_s))
    if moment.note:
        st.caption(moment.note)
