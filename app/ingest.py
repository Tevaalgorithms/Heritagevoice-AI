"""Ingestion job: stored audio -> draft transcript and translation, then wait for human review.

Progress (`stage`) is committed as each step finishes so the API can show it. Results are saved
in one transaction at the end. Provider failures raise `ProviderError` so the worker retries a
bounded number of times; a consent failure is final.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from functools import partial
from typing import cast

from sqlalchemy.orm import Session

from app.db.repositories import (
    ConsentRepository,
    JobRepository,
    RecordingRepository,
    TranscriptRepository,
)
from app.errors import ProviderError
from app.graph.preservation import build_preservation_graph
from app.graph.state import PreservationState
from app.models.job import Job, JobStatus, Outcome
from app.models.records import Consent, Recording, RecordingStatus, Right, TranslationVersion
from app.models.transcript import Segment
from app.ports import Transcriber, Translator
from app.security.consent import ConsentDeniedError, require_right
from app.transcript import validate_segments

SessionFactory = Callable[[], AbstractContextManager[Session]]
SYSTEM_ACTOR = "system:ingest"
PROVIDER_STAGES = {"asr", "mt"}


@dataclass(frozen=True)
class IngestDeps:
    """What the ingestion job needs: sessions, speech-to-text and the translator."""

    sessions: SessionFactory
    transcriber: Transcriber
    translator: Translator | None = None


def _consent_for(session: Session, recording: Recording | None) -> Consent | None:
    return None if recording is None else ConsentRepository(session).get(recording.consent_id)


def _load(job: Job, deps: IngestDeps) -> tuple[Recording, Consent]:
    with deps.sessions() as session:
        recording = RecordingRepository(session).get(job.recording_id or "")
        consent = _consent_for(session, recording)
    if recording is None or consent is None:
        raise ProviderError("recording or consent missing", code="missing_recording")
    return recording, consent


def _audio_key(recording: Recording) -> str:
    if recording.audio_key is None:
        raise ProviderError("recording has no stored audio", code="missing_recording")
    return recording.audio_key


def _set_stage(job: Job, stage: str, deps: IngestDeps) -> None:
    with deps.sessions() as session:
        JobRepository(session).set_stage(job.id, stage)


def _run_graph(
    job: Job, recording: Recording, consent: Consent, deps: IngestDeps
) -> PreservationState:
    graph = build_preservation_graph(deps.transcriber, deps.translator)
    state: PreservationState = {
        "recording_id": recording.id,
        "consent": consent,
        "audio_key": _audio_key(recording),
        "language": recording.language,
    }
    for update in graph.stream(state, stream_mode="updates"):
        node = next(iter(update))
        state = cast(PreservationState, {**state, **update[node]})
        _set_stage(job, node, deps)
    return state


def _save_translation(
    transcripts: TranscriptRepository, recording_id: str, version: int, segments: list[Segment]
) -> None:
    transcripts.save_translation_draft(
        TranslationVersion(
            id=f"{recording_id}:en:v{version}",
            recording_id=recording_id,
            transcript_version=version,
            version=version,
            target_language="en",
            segments=segments,
            created_by=SYSTEM_ACTOR,
        )
    )


def _ensure_still_allowed(session: Session, recording: Recording) -> None:
    """Consent or the recording may have been revoked while the job ran."""
    current = RecordingRepository(session).get(recording.id)
    if current is None or current.status == RecordingStatus.REVOKED:
        raise ConsentDeniedError("Recording was revoked")
    require_right(ConsentRepository(session).get(recording.consent_id), Right.AI_PROCESSING)


def _save(recording: Recording, state: PreservationState, deps: IngestDeps) -> None:
    segments = validate_segments(state["segments"], recording.duration_s)
    with deps.sessions() as session:
        _ensure_still_allowed(session, recording)
        transcripts = TranscriptRepository(session)
        draft = transcripts.save_draft(recording.id, segments, SYSTEM_ACTOR)
        if "translations" in state:
            _save_translation(transcripts, recording.id, draft.version, state["translations"])
        RecordingRepository(session).set_status(recording.id, RecordingStatus.REVIEW)


def _failed_outcome(state: PreservationState) -> Outcome:
    error = state.get("error")
    if error in PROVIDER_STAGES:
        raise ProviderError("provider step failed", code=str(error))
    return Outcome(status=JobStatus.FAILED, error=error)


def _gap_code(state: PreservationState) -> str | None:
    """`mt` on a review job means: transcript saved, translation missing."""
    return state.get("error") if _transcript_only(state) else None


def _transcript_only(state: PreservationState) -> bool:
    """Translation failed after a good transcript: keep the transcript, flag the gap with `mt`."""
    return state.get("error") == "mt" and "segments" in state


def ingest_recording(job: Job, deps: IngestDeps) -> Outcome:
    recording, consent = _load(job, deps)
    state = _run_graph(job, recording, consent, deps)
    if state.get("status") == JobStatus.FAILED and not _transcript_only(state):
        return _failed_outcome(state)
    try:
        _save(recording, state, deps)
    except ConsentDeniedError:
        return Outcome(status=JobStatus.FAILED, error="consent")
    return Outcome(status=JobStatus.REVIEW, error=_gap_code(state))


def ingest_handler(deps: IngestDeps) -> Callable[[Job], Outcome]:
    return partial(ingest_recording, deps=deps)
