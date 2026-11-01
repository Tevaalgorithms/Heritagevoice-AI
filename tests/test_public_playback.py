"""Playing audio without an account: only recordings shared publicly, and only while they are."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.api.auth import current_principal, get_session_factory
from app.api.main import app
from app.api.public import MEDIA_PER_MINUTE, get_media_limiter
from app.api.recordings import get_audio_store
from app.db.repositories import ConsentRepository
from app.db.session import session_scope
from app.db.tables import Base, RecordingRow
from app.fakes import FakeAudioStore
from app.models.records import RecordingStatus, Right, Visibility
from app.ratelimit import SlidingWindowLimiter
from app.revocation import revoke_recording
from tests.helpers import person, wav_bytes
from tests.index_helpers import published

AUDIO = wav_bytes(1.0)
PUBLIC_URL = "/v1/public/recordings/r1/media"
SIGNED_IN_URL = "/v1/recordings/r1/media"


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'playback.db'}")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def store():
    return FakeAudioStore()


@pytest.fixture
def visitor(engine, store):
    """A client with no credentials at all."""
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    app.dependency_overrides[get_audio_store] = lambda: store
    limiter = SlidingWindowLimiter(1000, 60.0)
    app.dependency_overrides[get_media_limiter] = lambda: limiter
    yield TestClient(app)
    app.dependency_overrides.clear()


def add(engine, store, **options):
    """A published recording with audio in storage."""
    options.setdefault("visibility", Visibility.PUBLIC)
    with session_scope(engine) as session:
        published(session, "r1", "c2", **options)
        session.get(RecordingRow, "r1").audio_key = "audio/r1"
    store.put("audio/r1", AUDIO, "audio/wav")


def test_a_visitor_plays_a_recording_shared_publicly(visitor, engine, store):
    add(engine, store)
    response = visitor.get(PUBLIC_URL)
    assert response.status_code == 200
    assert response.content == AUDIO
    assert response.headers["cache-control"] == "no-store"
    assert "noindex" in response.headers["x-robots-tag"]


def test_a_community_only_recording_is_not_found_for_a_visitor(visitor, engine, store):
    add(engine, store, visibility=Visibility.COMMUNITY)
    assert visitor.get(PUBLIC_URL).status_code == 404


@pytest.mark.parametrize("missing", [Right.PUBLIC_SHARING, Right.PLAYBACK])
def test_both_public_sharing_and_playback_consent_are_needed(visitor, engine, store, missing):
    add(engine, store, consent={"rights": [r for r in Right if r is not missing]})
    assert visitor.get(PUBLIC_URL).status_code == 404


def test_a_recording_still_in_review_cannot_be_played(visitor, engine, store):
    add(engine, store)
    with session_scope(engine) as session:
        session.get(RecordingRow, "r1").status = RecordingStatus.REVIEW
    assert visitor.get(PUBLIC_URL).status_code == 404


def test_withdrawn_consent_stops_playback_at_once(visitor, engine, store):
    add(engine, store)
    assert visitor.get(PUBLIC_URL).status_code == 200
    with session_scope(engine) as session:
        ConsentRepository(session).revoke("consent-1")
    assert visitor.get(PUBLIC_URL).status_code == 404


def test_a_taken_down_recording_stops_playing_at_once(visitor, engine, store):
    add(engine, store)
    with session_scope(engine) as session:
        revoke_recording(session, "r1")
    assert visitor.get(PUBLIC_URL).status_code == 404


def test_a_public_recording_without_stored_audio_is_not_found(visitor, engine, store):
    add(engine, store)
    with session_scope(engine) as session:
        session.get(RecordingRow, "r1").audio_key = None
    assert visitor.get(PUBLIC_URL).status_code == 404


def test_an_unknown_recording_looks_the_same_as_a_private_one(visitor, engine, store):
    add(engine, store, visibility=Visibility.COMMUNITY)
    private = visitor.get(PUBLIC_URL)
    unknown = visitor.get("/v1/public/recordings/nope/media")
    assert (private.status_code, private.json()) == (unknown.status_code, unknown.json())


def test_a_visitor_who_plays_too_often_is_slowed_down(engine, store):
    add(engine, store)
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    app.dependency_overrides[get_audio_store] = lambda: store
    limiter = SlidingWindowLimiter(MEDIA_PER_MINUTE, 60.0)
    app.dependency_overrides[get_media_limiter] = lambda: limiter
    try:
        client = TestClient(app)
        codes = [client.get(PUBLIC_URL).status_code for _ in range(MEDIA_PER_MINUTE + 1)]
    finally:
        app.dependency_overrides.clear()
    assert codes[:-1] == [200] * MEDIA_PER_MINUTE
    assert codes[-1] == 429


def test_a_signed_in_stranger_plays_a_public_recording_from_another_community(
    visitor, engine, store
):
    add(engine, store)
    app.dependency_overrides[current_principal] = lambda: person(
        user_id="stranger", communities=("c9",)
    )
    assert visitor.get(SIGNED_IN_URL).status_code == 200


def test_a_signed_in_stranger_cannot_play_a_community_only_recording(visitor, engine, store):
    add(engine, store, visibility=Visibility.COMMUNITY)
    app.dependency_overrides[current_principal] = lambda: person(
        user_id="stranger", communities=("c9",)
    )
    assert visitor.get(SIGNED_IN_URL).status_code == 404
