"""Throwing away a recording that nobody has approved: it must be really gone, and only for the
right person at the right time."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app.api.auth import current_principal, get_session_factory
from app.api.main import app
from app.api.recordings import get_audio_store
from app.audio import AudioRules
from app.db.repositories import (
    ConsentRepository,
    JobRepository,
    NewVersion,
    RecordingRepository,
    ReviewDecisionRepository,
    VersionRepository,
)
from app.db.session import session_scope
from app.db.tables import AuditLogRow, Base, TranscriptVersionRow
from app.fakes import FakeAudioStore
from app.models.job import JobStatus
from app.models.records import RecordingStatus, ReviewDecision, Subject
from app.models.transcript import Segment
from app.security.roles import Role
from app.uploads import UploadDeps, UploadRequest, accept_upload
from tests.helpers import consent, person, wav_bytes

RULES = AudioRules(max_bytes=5_000_000, max_seconds=600.0, languages=frozenset({"ta", "en"}))
AUDIO = wav_bytes(1.0)
OWNER = person(user_id="owner", communities=("c1",))
SEGMENT = Segment(segment_id="s1", start_s=0.0, end_s=1.0, text="தவறு")


@pytest.fixture
def store():
    return FakeAudioStore()


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'discard.db'}")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def client(engine, store):
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    app.dependency_overrides[get_audio_store] = lambda: store
    act_as(OWNER)
    yield TestClient(app)
    app.dependency_overrides.clear()


def act_as(principal):
    app.dependency_overrides[current_principal] = lambda: principal


def made(engine, store, processing=False):
    """A recording the owner made. By default it has finished processing and has a draft."""
    with session_scope(engine) as session:
        ConsentRepository(session).add(consent("consent-1", "c1"))
    deps = UploadDeps(lambda: session_scope(engine), store, RULES)
    accepted = accept_upload(
        UploadRequest(OWNER, "c1", "ta", "consent-1", "key-00000001", AUDIO), deps
    )
    with session_scope(engine) as session:
        if not processing:
            JobRepository(session).set_status(accepted.job_id, JobStatus.REVIEW)
        draft = NewVersion(accepted.recording_id, Subject.TRANSCRIPT, [SEGMENT], "system")
        VersionRepository(session).add_draft(draft)
        RecordingRepository(session).set_status(accepted.recording_id, RecordingStatus.REVIEW)
    return accepted.recording_id


def discard(client, recording_id):
    return client.delete(f"/v1/recordings/{recording_id}")


def test_the_owner_discards_a_recording_and_everything_about_it_is_erased(client, engine, store):
    rid = made(engine, store)
    assert len(store.objects) == 1
    assert discard(client, rid).status_code == 204
    assert not store.objects
    with session_scope(engine) as session:
        assert RecordingRepository(session).get(rid) is None
        assert JobRepository(session).by_recording(rid) is None
        assert session.scalars(select(TranscriptVersionRow)).first() is None
    assert client.get(f"/v1/recordings/{rid}").status_code == 404


def test_the_audit_log_notes_who_discarded_it_and_which_recording_but_nothing_said(
    client, engine, store
):
    rid = made(engine, store)
    discard(client, rid)
    with session_scope(engine) as session:
        entry = session.scalars(select(AuditLogRow)).one()
        assert (entry.actor_sub, entry.action, entry.target) == (
            "owner",
            "recording:discard",
            f"recording:{rid}",
        )
        assert "தவறு" not in str(entry.detail)


def test_someone_else_in_the_group_cannot_discard_it(client, engine, store):
    rid = made(engine, store)
    act_as(person(user_id="neighbour", communities=("c1",)))
    assert discard(client, rid).status_code == 404
    assert len(store.objects) == 1


def test_a_coordinator_cannot_discard_someone_elses_recording(client, engine, store):
    rid = made(engine, store)
    act_as(person(Role.REVIEWER, user_id="coordinator", communities=("c1",)))
    assert discard(client, rid).status_code == 404
    assert len(store.objects) == 1


def test_an_admin_may_discard_an_unapproved_recording(client, engine, store):
    rid = made(engine, store)
    act_as(person(Role.ADMIN, user_id="admin-1", communities=()))
    assert discard(client, rid).status_code == 204
    assert not store.objects


def test_a_recording_that_is_being_processed_is_not_discarded(client, engine, store):
    rid = made(engine, store, processing=True)
    response = discard(client, rid)
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "still_processing")
    assert len(store.objects) == 1


def test_a_published_recording_cannot_be_discarded(client, engine, store):
    rid = made(engine, store)
    with session_scope(engine) as session:
        RecordingRepository(session).set_status(rid, RecordingStatus.PUBLISHED)
    response = discard(client, rid)
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "already_shared")
    assert len(store.objects) == 1


def test_a_recording_that_was_ever_approved_cannot_be_discarded_even_if_back_in_review(
    client, engine, store
):
    rid = made(engine, store)
    with session_scope(engine) as session:
        decision = ReviewDecision(
            id="d1",
            recording_id=rid,
            subject=Subject.TRANSCRIPT,
            subject_version=1,
            reviewer_id="admin-1",
            approved=True,
        )
        ReviewDecisionRepository(session).add(decision)
    response = discard(client, rid)
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "already_shared")


def test_an_unknown_recording_is_not_found(client):
    assert discard(client, "nope").status_code == 404


def test_when_the_audio_cannot_be_deleted_nothing_is_erased(client, engine, store, monkeypatch):
    rid = made(engine, store)

    def broken(key):
        raise OSError("storage down")

    monkeypatch.setattr(store, "delete", broken)
    assert discard(client, rid).status_code == 500
    with session_scope(engine) as session:
        assert RecordingRepository(session).get(rid) is not None
