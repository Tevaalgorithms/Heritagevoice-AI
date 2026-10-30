"""Where a recording's audio comes from (the microphone or a file) and how it is keyed."""

import hashlib
from typing import Protocol


class AudioSource(Protocol):
    """Anything Streamlit hands back for audio: a microphone recording or an uploaded file."""

    def getvalue(self) -> bytes: ...


def pick_audio(recorded: AudioSource | None, file: AudioSource | None) -> bytes | None:
    """The audio to send. A fresh microphone recording wins over a file left in the other tab."""
    chosen = recorded if recorded is not None else file
    return None if chosen is None else chosen.getvalue()


def idempotency_key(data: bytes) -> str:
    """One key per distinct recording: sending the same audio twice is a duplicate, never two
    uploads, while a new recording in the same session gets a new key."""
    return "up-" + hashlib.sha256(data).hexdigest()[:32]
