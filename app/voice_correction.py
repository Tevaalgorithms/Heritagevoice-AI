"""Correct a proposed relationship by speaking: transcribe, translate, then interpret.

The reviewer's audio is stored only for the length of this call and is always deleted afterwards,
whatever happens. Nothing is saved: the result goes back to the reviewer, who checks it and
approves it through the normal review step. The recording the proposal came from is not touched.
"""

from dataclasses import dataclass, replace
from uuid import uuid4

from app.agents.correction_interpreter import CorrectionInterpreter, Interpretation
from app.audio import AudioRules, check_language, validate_audio
from app.models.records import GraphAssertion
from app.models.transcript import Segment
from app.ports import AudioStore, Transcriber, Translator

ENGLISH = "en"
VOICE_MAX_SECONDS = 60.0  # a correction is a sentence or two, not a story


@dataclass(frozen=True)
class VoiceDeps:
    """What understanding a spoken correction needs."""

    store: AudioStore
    transcriber: Transcriber
    translator: Translator
    interpreter: CorrectionInterpreter
    rules: AudioRules


@dataclass(frozen=True)
class Spoken:
    """The reviewer's recording and the language it is in."""

    data: bytes
    language: str


@dataclass(frozen=True)
class VoiceFix:
    """What was heard (in the reviewer's language and in English) and what it was taken to mean."""

    heard: str
    english: str
    suggestion: Interpretation | None


def _words(segments: list[Segment]) -> str:
    return " ".join(segment.text for segment in segments).strip()


def _transcribe(spoken: Spoken, assertion_id: str, deps: VoiceDeps) -> list[Segment]:
    key = f"corrections/{assertion_id}/{uuid4().hex}"
    deps.store.put(key, spoken.data, "application/octet-stream")
    try:
        return deps.transcriber.transcribe(key, spoken.language)
    finally:
        deps.store.delete(key)


def _in_english(segments: list[Segment], language: str, deps: VoiceDeps) -> str:
    if language == ENGLISH or not segments:
        return _words(segments)
    return _words(deps.translator.translate(segments, ENGLISH))


def understand_correction(
    assertion: GraphAssertion, passage: str, spoken: Spoken, deps: VoiceDeps
) -> VoiceFix:
    rules = replace(deps.rules, max_seconds=min(deps.rules.max_seconds, VOICE_MAX_SECONDS))
    check_language(spoken.language, rules)
    validate_audio(spoken.data, rules)
    segments = _transcribe(spoken, assertion.id, deps)
    heard = _words(segments)
    if not heard:
        return VoiceFix("", "", None)
    english = _in_english(segments, spoken.language, deps)
    return VoiceFix(heard, english, deps.interpreter.interpret(assertion, passage, heard, english))
