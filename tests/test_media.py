import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.api.auth import current_principal, get_session_factory
from app.api.main import app
from app.api.recordings import get_audio_store
from app.audio import AudioRules
from app.db.repositories import ConsentRepository
from app.db.session import session_scope
from app.db.tables import Base
from app.fakes import FakeAudioStore
from app.models.records import Right
from app.revocation import revoke_recording
from app.security.roles import Role
from app.uploads import UploadDeps, UploadRequest, accept_upload
from tests.helpers import consent, person, wav_bytes

RULES = AudioRules(max_bytes=5_000_000, max_seconds=600.0, languages=frozenset({"ta", "en"}))
AUDIO = wav_bytes(1.0)


@pytest.fixture
def store():
    return FakeAudioStore()


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'media.db'}")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def client(engine, store):
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    app.dependency_overrides[get_audio_store] = lambda: store
    act_as(person())
    yield TestClient(app)
    app.dependency_overrides.clear()


def recording(engine, store, rights=tuple(Right)):
    with session_scope(engine) as session:
        ConsentRepository(session).add(consent("consent-1", "c1", rights=rights))
    deps = UploadDeps(lambda: session_scope(engine), store, RULES)
    request = UploadRequest(person(), "c1", "ta", "consent-1", "key-00000001", AUDIO)
    return accept_upload(request, deps).recording_id


def act_as(principal):
    app.dependency_overrides[current_principal] = lambda: principal


def test_a_member_of_the_group_plays_the_audio(client, engine, store):
    rid = recording(engine, store)
    response = client.get(f"/v1/recordings/{rid}/media")
    assert response.status_code == 200
    assert response.content == AUDIO
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["cache-control"] == "private, no-store"


def test_an_admin_can_play_it(client, engine, store):
    rid = recording(engine, store)
    act_as(person(Role.ADMIN, user_id="admin-1", communities=()))
    assert client.get(f"/v1/recordings/{rid}/media").status_code == 200


def test_someone_outside_the_group_gets_nothing(client, engine, store):
    rid = recording(engine, store)
    act_as(person(user_id="stranger", communities=("c2",)))
    assert client.get(f"/v1/recordings/{rid}/media").status_code == 404


def test_without_the_playback_right_there_is_no_audio(client, engine, store):
    rid = recording(engine, store, rights=(Right.AI_PROCESSING, Right.TRANSLATION))
    assert client.get(f"/v1/recordings/{rid}/media").status_code == 404


def test_a_revoked_recording_cannot_be_played(client, engine, store):
    rid = recording(engine, store)
    with session_scope(engine) as session:
        revoke_recording(session, rid)
    assert client.get(f"/v1/recordings/{rid}/media").status_code == 404


def test_an_unknown_recording_is_404(client):
    assert client.get("/v1/recordings/nope/media").status_code == 404
