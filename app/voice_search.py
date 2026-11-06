"""Search by voice: turn a few spoken words into text for the search box.

The recording is held only while it is transcribed and is always deleted afterwards. Nothing is
saved or logged: the words go back to the person, who sees them in the box and searches as usual.
Used by signed-in readers and by visitors, so the clip is kept short and small.
"""

from dataclasses import dataclass, replace
from uuid import uuid4

from app.audio import AudioRules, check_language, validate_audio
from app.ports import AudioStore, Transcriber
from app.voice_correction import Spoken

SEARCH_MAX_SECONDS = 15.0  # a name or an idea, not a story
SEARCH_MAX_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class SearchVoiceDeps:
    """What hearing a spoken search needs."""

    store: AudioStore
    transcriber: Transcriber
    rules: AudioRules


def short_rules(rules: AudioRules) -> AudioRules:
    """The upload rules, tightened to a few seconds and a few megabytes."""
    return replace(
        rules,
        max_seconds=min(rules.max_seconds, SEARCH_MAX_SECONDS),
        max_bytes=min(rules.max_bytes, SEARCH_MAX_BYTES),
    )


def hear(spoken: Spoken, deps: SearchVoiceDeps) -> str:
    """The words in the clip, or an empty string if nothing could be made out."""
    rules = short_rules(deps.rules)
    check_language(spoken.language, rules)
    validate_audio(spoken.data, rules)
    key = f"searches/{uuid4().hex}"
    deps.store.put(key, spoken.data, "application/octet-stream")
    try:
        segments = deps.transcriber.transcribe(key, spoken.language)
    finally:
        deps.store.delete(key)
    return " ".join(segment.text for segment in segments).strip()
