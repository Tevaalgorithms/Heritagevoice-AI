"""The background job that proposes graph relationships for a published recording.

It runs only while the recording is published and its consent still allows AI processing, reads
the transcript that is approved now, and stores what the model proposes as *pending*. Nothing here
publishes anything: a person approves each proposal before it can reach the graph.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.agents.graph_extractor import GraphExtractor, Source
from app.db.repositories import (
    ConsentRepository,
    GraphAssertionRepository,
    RecordingRepository,
    VersionRepository,
)
from app.models.job import Job, JobStatus, Outcome
from app.models.records import Consent, Recording, RecordingStatus, Right, Subject

EXTRACT_KIND = "extract_graph"
SessionFactory = Callable[[], AbstractContextManager[Session]]


class ExtractionRefusedError(Exception):
    """This recording must not be read by a model now; `code` says why (a short, safe label)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ExtractDeps:
    """What the job needs: database sessions and the extractor."""

    sessions: SessionFactory
    extractor: GraphExtractor


def _published(session: Session, recording_id: str) -> Recording:
    recording = RecordingRepository(session).get(recording_id)
    if recording is None:
        raise ExtractionRefusedError("missing")
    if recording.status != RecordingStatus.PUBLISHED:
        raise ExtractionRefusedError("not_published")
    return recording


def _consent(session: Session, recording: Recording) -> Consent:
    consent = ConsentRepository(session).get(recording.consent_id)
    if consent is None or not consent.permits(Right.AI_PROCESSING):
        raise ExtractionRefusedError("consent")
    return consent


def _source(session: Session, recording_id: str) -> Source:
    recording = _published(session, recording_id)
    consent = _consent(session, recording)
    transcript = VersionRepository(session).approved(recording.id, Subject.TRANSCRIPT)
    if transcript is None:
        raise ExtractionRefusedError("not_approved")
    return Source(recording.id, transcript.version, consent.policy_version, transcript.segments)


def extract_one(deps: ExtractDeps, recording_id: str) -> int:
    """Propose relationships for one recording; returns how many new proposals were stored."""
    with deps.sessions() as session:
        source = _source(session, recording_id)
    proposed = deps.extractor.extract(source)  # the model call happens outside any transaction
    with deps.sessions() as session:
        return GraphAssertionRepository(session).replace_pending(
            source.recording_id, source.transcript_version, proposed
        )


def extract_recording(job: Job, deps: ExtractDeps) -> Outcome:
    try:
        extract_one(deps, job.recording_id or "")
    except ExtractionRefusedError as refusal:
        return Outcome(status=JobStatus.FAILED, error=refusal.code)
    return Outcome(status=JobStatus.PUBLISHED)
