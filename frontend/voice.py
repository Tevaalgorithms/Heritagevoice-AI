"""Search by voice, shared by the pages that offer it: send a short clip, get the words back."""

import streamlit as st

from frontend.api_client import ApiClient, ApiError
from frontend.messages import message_for
from frontend.spoken import LANGUAGE_CHOICES

NOTHING_HEARD = "I could not make out any words. Try again, a little closer and slower."
HELP = (
    "Pick your language, record a few words, and they appear in the box. The recording is deleted "
    "as soon as it has been understood. It needs no account."
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
