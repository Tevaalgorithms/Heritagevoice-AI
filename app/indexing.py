"""Index approved, published content for search, and remove it again when it must disappear.

PostgreSQL gets the chunks (keyword search and the source of truth); Pinecone gets vectors when it
is configured. Indexing happens in background jobs, but removal does not wait: the chunk rows are
deleted in the same transaction as a correction or revocation (see `index_sync`), so keyword
results vanish at once, and vector results are re-checked against PostgreSQL before use anyway.
"""

import hashlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.repositories import (
    ChunkRepository,
    ConsentRepository,
    GraphAssertionRepository,
    RecordingRepository,
    VersionRepository,
)
from app.models.index import ChunkKind, ChunkRecord
from app.models.job import Job, JobStatus, Outcome
from app.models.records import (
    GraphAssertion,
    Recording,
    RecordingStatus,
    Right,
    Subject,
    VersionRef,
    Visibility,
)
from app.ports import GraphProjection, VectorStore
from app.retrieval.chunker import chunk_segments
from app.retrieval.evidence_store import to_evidence

INDEX_KIND = "index_recording"
UNINDEX_KIND = "unindex_recording"
TRANSLATION_LANGUAGE = "en"

SessionFactory = Callable[[], AbstractContextManager[Session]]


class IndexRefusedError(Exception):
    """This recording must not be indexed; `code` says why (a short, safe label)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class IndexDeps:
    """What the indexing jobs need: database sessions and the vector store."""

    sessions: SessionFactory
    vectors: VectorStore | None = None
    graph: GraphProjection | None = None


def _records(
    recording: Recording, version: VersionRef, kind: ChunkKind, language: str
) -> list[ChunkRecord]:
    """Chunks of one version; they carry the recording's (already consent-checked) visibility."""
    records = []
    for chunk in chunk_segments(version.segments):
        records.append(
            ChunkRecord(
                evidence_id=f"{recording.id}:{kind.value}:v{version.version}:c{chunk.index}",
                recording_id=recording.id,
                community_id=recording.community_id,
                kind=kind,
                version=version.version,
                chunk_index=chunk.index,
                language=language,
                text=chunk.text,
                passage_hash=hashlib.sha256(chunk.text.encode()).hexdigest(),
                start_s=chunk.start_s,
                end_s=chunk.end_s,
                segment_ids=chunk.segment_ids,
                speaker=chunk.speaker,
                visibility=recording.visibility,
            )
        )
    return records


def _consented(session: Session, recording: Recording) -> Recording:
    """The recording as it may be indexed: public only if the consent allows public sharing."""
    consent = ConsentRepository(session).get(recording.consent_id)
    if consent is not None and consent.permits(Right.PUBLIC_SHARING):
        return recording
    return recording.model_copy(update={"visibility": Visibility.COMMUNITY})


def build_records(session: Session, original: Recording) -> list[ChunkRecord]:
    """Chunks of the approved transcript, plus the approved translation if it matches it."""
    recording = _consented(session, original)
    versions = VersionRepository(session)
    transcript = versions.approved(recording.id, Subject.TRANSCRIPT)
    if transcript is None:
        raise IndexRefusedError("not_approved")
    records = _records(recording, transcript, ChunkKind.TRANSCRIPT, recording.language)
    translation = versions.approved(recording.id, Subject.TRANSLATION)
    if translation is not None and translation.transcript_version == transcript.version:
        records += _records(recording, translation, ChunkKind.TRANSLATION, TRANSLATION_LANGUAGE)
    return records


def _indexable(session: Session, recording_id: str) -> Recording:
    recording = RecordingRepository(session).get(recording_id)
    if recording is None:
        raise IndexRefusedError("missing")
    if recording.status != RecordingStatus.PUBLISHED:
        raise IndexRefusedError("not_published")
    consent = ConsentRepository(session).get(recording.consent_id)
    if consent is None or not consent.permits(Right.INDEXING):
        raise IndexRefusedError("consent")
    return recording


def _sync_vectors(deps: IndexDeps, recording: Recording, records: list[ChunkRecord]) -> None:
    if deps.vectors is None:
        return
    deps.vectors.delete_recording(recording.id, recording.community_id)
    deps.vectors.upsert([to_evidence(record, "vector") for record in records])


def _current_assertions(session: Session, recording: Recording) -> list[GraphAssertion]:
    """Approved assertions about the transcript that is approved now; older ones are stale."""
    transcript = VersionRepository(session).approved(recording.id, Subject.TRANSCRIPT)
    if transcript is None:
        return []
    approved = GraphAssertionRepository(session).approved_for(recording.id)
    return [a for a in approved if a.transcript_version == transcript.version]


def project_graph(deps: IndexDeps, recording_id: str) -> int:
    """Make the knowledge graph hold this recording's approved assertions, or nothing if it may
    not be read. Returns how many assertions were written. Safe to repeat."""
    if deps.graph is None:
        return 0
    with deps.sessions() as session:
        try:
            recording = _consented(session, _indexable(session, recording_id))
        except IndexRefusedError:
            deps.graph.delete_recording(recording_id)
            return 0
        assertions = _current_assertions(session, recording)
    deps.graph.replace_recording(
        recording.id, recording.community_id, recording.visibility, assertions
    )
    return len(assertions)


def index_one(deps: IndexDeps, recording_id: str) -> int:
    """(Re)build the index of one published recording; returns the number of chunks."""
    with deps.sessions() as session:
        recording = _indexable(session, recording_id)
        records = build_records(session, recording)
        ChunkRepository(session).replace_for_recording(recording.id, records)
    _sync_vectors(deps, recording, records)
    project_graph(deps, recording_id)
    return len(records)


def index_recording(job: Job, deps: IndexDeps) -> Outcome:
    try:
        index_one(deps, job.recording_id or "")
    except IndexRefusedError as refusal:
        return Outcome(status=JobStatus.FAILED, error=refusal.code)
    return Outcome(status=JobStatus.PUBLISHED)


def remove_recording(deps: IndexDeps, recording_id: str) -> bool:
    """Remove a recording from both indexes. False if it is unknown. Safe to repeat."""
    with deps.sessions() as session:
        recording = RecordingRepository(session).get(recording_id)
        if recording is None:
            return False
        ChunkRepository(session).delete_for_recording(recording.id)
    if deps.vectors is not None:
        deps.vectors.delete_recording(recording.id, recording.community_id)
    if deps.graph is not None:
        deps.graph.delete_recording(recording.id)
    return True


def unindex_recording(job: Job, deps: IndexDeps) -> Outcome:
    if not remove_recording(deps, job.recording_id or ""):
        return Outcome(status=JobStatus.FAILED, error="missing")
    return Outcome(status=JobStatus.PUBLISHED)
