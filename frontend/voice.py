"""Search by voice, shared by the pages that offer it: send a short clip, get the words back."""

import hashlib

import streamlit as st

from frontend.api_client import ApiClient, ApiError
from frontend.messages import message_for
from frontend.spoken import LANGUAGE_CHOICES

NOTHING_HEARD = "I could not make out any words. Try again, a little closer and slower."
HELP = (
    "Pick your language, press the microphone, say a few words and stop. They appear in the search "
    "box by themselves. The recording is deleted as soon as it has been understood. It needs no "
    "account."
)


def heard_words(client: ApiClient, language: str, audio: bytes) -> str:
    """The words in the clip, or an empty string after telling the person what went wrong."""
    try:
        with st.spinner("Listening…"):
            heard = client.hear_search(audio, LANGUAGE_CHOICES[language])
    except ApiError as error:
        st.error(message_for(error))
        return ""
    if not heard:
        st.warning(NOTHING_HEARD)
    return heard


def hear_once(client: ApiClient, language: str, clip: bytes, page: str) -> None:
    """Understand a new recording and leave its words under `{page}-heard` for the page's search
    box, then run the page again. The same recording is never sent twice, because Streamlit runs
    the page again after every click."""
    digest = hashlib.sha256(clip).hexdigest()
    done = f"{page}-voice-done"
    if st.session_state.get(done) == digest:
        return
    st.session_state[done] = digest
    heard = heard_words(client, language, clip)
    if heard:
        st.session_state[f"{page}-heard"] = heard
        st.rerun()
