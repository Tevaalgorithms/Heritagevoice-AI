import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.audio import AudioRules
from app.db.repositories import (
    ConsentRepository,
    JobRepository,
    RecordingRepository,
    TranscriptRepository,
)
from app.db.session import session_scope
from app.db.tables import Base
from app.errors import ProviderError
from app.fakes import FakeAudioStore, FakeTranscriber, FakeTranslator, FakeVectorStore
from app.ingest import IngestDeps, ingest_handler
from app.models.job import JobStatus
from app.models.records import RecordingStatus, VersionStatus
from app.models.transcript import Segment
from app.transcript import validate_segments
from app.uploads import UploadDeps, UploadRequest, accept_upload
from app.worker import MAX_ATTEMPTS, process_next
from tests.helpers import consent, person, wav_bytes

RULES = AudioRules(max_bytes=5_000_000, max_seconds=600.0, languages=frozenset({"ta", "en"}))
GOOD = [
    Segment(segment_id="s1", start_s=0.0, end_s=0.5, text="vanakkam"),
    Segment(segment_id="s2", start_s=0.5, end_s=0.9, text="nandri"),
]


class RecordingTranscriber(FakeTranscriber):
    def __init__(self, segments):
        super().__init__(segments)
        self.calls = 0

    def transcribe(self, audio_key, language):
        self.calls += 1
        return super().transcribe(audio_key, language)


class FailingTranscriber:
    def __init__(self):
        self.calls = 0

    def transcribe(self, audio_key, language):
        self.calls += 1
        raise ProviderError("timeout with private detail", code="asr")


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ingest.db'}")
    Base.metadata.create_all(engine)
    with session_scope(engine) as session:
        ConsentRepository(session).add(consent())
    return engine


def sessions(engine):
    return lambda: session_scope(engine)


def upload(engine):
    deps = UploadDeps(sessions(engine), FakeAudioStore(), RULES)
    request = UploadRequest(person(), "c1", "ta", "consent-1", "key-00000001", wav_bytes(1.0))
    return accept_upload(request, deps)


def run(engine, transcriber, translator=None):
    handlers = {
        "ingest_recording": ingest_handler(IngestDeps(sessions(engine), transcriber, translator))
    }
    return process_next(engine, handlers)


def job_and_recording(engine, accepted):
    with Session(engine) as session:
        return (
            JobRepository(session).get(accepted.job_id),
            RecordingRepository(session).get(accepted.recording_id),
        )


def test_an_upload_becomes_a_timed_draft_transcript_waiting_for_review(engine):
    accepted = upload(engine)
    transcriber = RecordingTranscriber(GOOD)
    assert run(engine, transcriber)
    job, recording = job_and_recording(engine, accepted)
    assert (job.status, job.stage, job.error) == (JobStatus.REVIEW, "transcribe", None)
    assert recording.status == RecordingStatus.REVIEW
    with Session(engine) as session:
        draft = TranscriptRepository(session).latest(accepted.recording_id)
    assert (draft.version, draft.status) == (1, VersionStatus.DRAFT)
    assert [(s.segment_id, s.start_s, s.end_s) for s in draft.segments] == [
        ("s1", 0.0, 0.5),
        ("s2", 0.5, 0.9),
    ]


def test_a_draft_transcript_is_excluded_from_every_search_path(engine):
    accepted = upload(engine)
    run(engine, RecordingTranscriber(GOOD))
    with Session(engine) as session:
        assert TranscriptRepository(session).approved_segments(accepted.recording_id) == []
    assert FakeVectorStore().search("vanakkam", person()) == []


def test_a_translation_draft_is_saved_when_a_translator_is_configured(engine):
    accepted = upload(engine)
    run(engine, RecordingTranscriber(GOOD), FakeTranslator())
    with Session(engine) as session:
        translation = TranscriptRepository(session).latest_translation(accepted.recording_id)
    assert translation.status == VersionStatus.DRAFT
    assert [s.text for s in translation.segments] == ["[en] vanakkam", "[en] nandri"]


def test_provider_failures_are_retried_a_bounded_number_of_times_then_fail_safely(engine):
    accepted = upload(engine)
    transcriber = FailingTranscriber()
    for _ in range(MAX_ATTEMPTS):
        assert run(engine, transcriber)
    assert not run(engine, transcriber)
    job, recording = job_and_recording(engine, accepted)
    assert (job.status, job.error, job.attempts) == (JobStatus.FAILED, "asr", MAX_ATTEMPTS)
    assert transcriber.calls == MAX_ATTEMPTS
    assert recording.status == RecordingStatus.DRAFT
    with Session(engine) as session:
        assert TranscriptRepository(session).latest(accepted.recording_id) is None


def test_consent_revoked_after_upload_stops_processing_before_any_provider_call(engine):
    accepted = upload(engine)
    with session_scope(engine) as session:
        session.execute(text("update consent set revoked = 1 where id = 'consent-1'"))
    transcriber = RecordingTranscriber(GOOD)
    run(engine, transcriber)
    job, _ = job_and_recording(engine, accepted)
    assert (job.status, job.error, job.attempts) == (JobStatus.FAILED, "consent", 1)
    assert transcriber.calls == 0


def test_a_withdrawn_ai_processing_right_is_final_not_retried(engine):
    accepted = upload(engine)
    with session_scope(engine) as session:
        session.execute(text("update consent set rights = '[\"playback\"]'"))
    transcriber = RecordingTranscriber(GOOD)
    run(engine, transcriber)
    job, _ = job_and_recording(engine, accepted)
    assert (job.status, job.error) == (JobStatus.FAILED, "consent")
    assert transcriber.calls == 0


@pytest.mark.parametrize(
    "segments",
    [
        [],
        [
            Segment(segment_id="s1", start_s=0.0, end_s=0.6, text="a"),
            Segment(segment_id="s2", start_s=0.5, end_s=0.9, text="b"),
        ],
        [
            Segment(segment_id="s1", start_s=0.0, end_s=0.4, text="a"),
            Segment(segment_id="s1", start_s=0.5, end_s=0.9, text="b"),
        ],
        [
            Segment(
                segment_id="s1", start_s=0.0, end_s=900.0, text="past the end of a 1 second file"
            )
        ],
    ],
    ids=["empty", "overlap", "duplicate-ids", "beyond-audio"],
)
def test_invalid_transcripts_are_never_saved(engine, segments):
    accepted = upload(engine)
    for _ in range(MAX_ATTEMPTS):
        run(engine, RecordingTranscriber(segments))
    job, recording = job_and_recording(engine, accepted)
    assert (job.status, job.error) == (JobStatus.FAILED, "asr")
    assert recording.status == RecordingStatus.DRAFT
    with Session(engine) as session:
        assert TranscriptRepository(session).latest(accepted.recording_id) is None


def test_validate_segments_accepts_adjacent_segments_and_unknown_duration():
    assert validate_segments(GOOD, None) == GOOD
    assert validate_segments(GOOD, 0.9) == GOOD
