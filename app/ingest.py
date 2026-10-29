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
from app.models.records import Consent, Recording, RecordingStatus, TranslationVersion
from app.models.transcript import Segment
from app.ports import Transcriber, Translator
from app.transcript import validate_segments

SessionFactory = Callable[[], AbstractContextManager[Session]]
SYSTEM_ACTOR = "system:ingest"
PROVIDER_STAGES = {"asr", "mt"}


@dataclass(frozen=True)
class IngestDeps:
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


def _save(recording: Recording, state: PreservationState, deps: IngestDeps) -> None:
    segments = validate_segments(state["segments"], recording.duration_s)
    with deps.sessions() as session:
        transcripts = TranscriptRepository(session)
        draft = transcripts.save_draft(recording.id, segments, SYSTEM_ACTOR)
        if "translations" in state:
            _save_translation(transcripts, recording.id, draft.version, state["translations"])
        RecordingRepository(session).set_status(recording.id, RecordingStatus.REVIEW)


def ingest_recording(job: Job, deps: IngestDeps) -> Outcome:
    recording, consent = _load(job, deps)
    state = _run_graph(job, recording, consent, deps)
    error = state.get("error")
    if state.get("status") == JobStatus.FAILED:
        if error in PROVIDER_STAGES:
            raise ProviderError("provider step failed", code=str(error))
        return Outcome(status=JobStatus.FAILED, error=error)
    _save(recording, state, deps)
    return Outcome(status=JobStatus.REVIEW)


def ingest_handler(deps: IngestDeps) -> Callable[[Job], Outcome]:
    return partial(ingest_recording, deps=deps)
