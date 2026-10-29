import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.api.auth import current_principal, get_session_factory
from app.api.main import app
from app.api.recordings import get_audio_store
from app.db.repositories import ConsentRepository, JobRepository, RecordingRepository
from app.db.session import session_scope
from app.db.tables import Base, JobRow, RecordingRow
from app.fakes import FakeAudioStore
from app.models.job import JobStatus
from app.models.records import Right
from app.security.roles import Role
from tests.helpers import consent, person, wav_bytes


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rec.db'}")
    Base.metadata.create_all(engine)
    with session_scope(engine) as session:
        repo = ConsentRepository(session)
        repo.add(consent("consent-1", "c1"))
        repo.add(consent("consent-c2", "c2"))
        repo.add(consent("consent-noai", "c1", rights=[Right.PLAYBACK, Right.TRANSLATION]))
        repo.add(consent("consent-notr", "c1", rights=[Right.AI_PROCESSING]))
        repo.add(consent("consent-revoked", "c1", revoked=True))
    return engine


@pytest.fixture
def store():
    return FakeAudioStore()


@pytest.fixture
def client(engine, store, monkeypatch):
    monkeypatch.setenv("HERITAGEVOICE_MAX_AUDIO_MB", "1")
    monkeypatch.setenv("HERITAGEVOICE_MAX_AUDIO_MINUTES", "1")
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    app.dependency_overrides[get_audio_store] = lambda: store
    app.dependency_overrides[current_principal] = person
    yield TestClient(app)
    app.dependency_overrides.clear()


def act_as(principal):
    app.dependency_overrides[current_principal] = lambda: principal


def upload(client, data=None, key="key-00000001", **form):
    fields = {"language": "ta", "community_id": "c1", "consent_id": "consent-1", **form}
    files = {"file": ("anything.wav", data if data is not None else wav_bytes(), "audio/wav")}
    return client.post("/v1/recordings", data=fields, files=files, headers={"Idempotency-Key": key})


def count(engine, table):
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(table))


def test_a_valid_upload_stores_the_audio_and_queues_one_job(client, engine, store):
    response = upload(client)
    assert response.status_code == 201
    ids = response.json()
    (key,) = store.objects
    assert key == f"recordings/c1/{ids['recording_id']}/original"
    assert store.objects[key][1] == "audio/wav"
    with Session(engine) as session:
        recording = RecordingRepository(session).get(ids["recording_id"])
        job = JobRepository(session).get(ids["job_id"])
    assert (recording.status, recording.uploader_id, recording.language) == ("draft", "u1", "ta")
    assert recording.duration_s == pytest.approx(1.0, abs=0.05)
    assert (job.status, job.kind, job.recording_id) == (
        JobStatus.QUEUED,
        "ingest_recording",
        recording.id,
    )


def test_the_storage_key_never_contains_the_file_name(client, store):
    upload(client)
    assert all("anything" not in key and ".wav" not in key for key in store.objects)


def test_repeating_an_upload_with_the_same_key_returns_the_same_result(client, engine, store):
    first = upload(client)
    second = upload(client)
    assert (second.status_code, second.json()) == (200, first.json())
    assert (len(store.objects), count(engine, RecordingRow), count(engine, JobRow)) == (1, 1, 1)


def test_the_same_key_from_another_user_is_a_separate_upload(client, engine):
    upload(client)
    act_as(person(user_id="u2"))
    assert upload(client).status_code == 201
    assert count(engine, RecordingRow) == 2


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"form": {"language": "fr"}}, (422, "bad_language")),
        ({"data": b"this is plain text, not audio"}, (415, "unsupported_type")),
        ({"data": b"MZ" + b"\x00" * 200}, (415, "unsupported_type")),
        ({"data": wav_bytes(90.0, 1000)}, (422, "too_long")),
        ({"data": wav_bytes(1.0, 600_000)}, (413, "too_large")),
    ],
    ids=["language", "text", "executable", "too-long", "too-large"],
)
def test_invalid_input_is_rejected_before_anything_is_stored(client, engine, kwargs, expected):
    response = upload(client, kwargs.get("data"), **kwargs.get("form", {}))
    assert (response.status_code, response.json()["detail"]["code"]) == expected
    assert (count(engine, RecordingRow), count(engine, JobRow)) == (0, 0)
    assert len(app.dependency_overrides[get_audio_store]().objects) == 0


@pytest.mark.parametrize(
    "consent_id",
    ["consent-missing", "consent-c2", "consent-noai", "consent-notr", "consent-revoked"],
)
def test_missing_wrong_or_revoked_consent_stops_the_upload(client, engine, store, consent_id):
    response = upload(client, consent_id=consent_id)
    assert (response.status_code, response.json()["detail"]["code"]) == (403, "consent_denied")
    assert (len(store.objects), count(engine, RecordingRow)) == (0, 0)


@pytest.mark.parametrize(
    "principal",
    [
        person(communities=("c2",)),
        person(Role.ADMIN, communities=()),
        person(communities=()),
    ],
    ids=["other-community", "admin", "no-community"],
)
def test_only_community_members_may_upload(client, engine, store, principal):
    act_as(principal)
    response = upload(client)
    assert (response.status_code, response.json()["detail"]["code"]) == (403, "forbidden")
    assert len(store.objects) == 0


def test_the_idempotency_key_is_required_and_checked(client):
    files = {"file": ("a.wav", wav_bytes(), "audio/wav")}
    form = {"language": "ta", "community_id": "c1", "consent_id": "consent-1"}
    assert client.post("/v1/recordings", data=form, files=files).status_code == 422
    bad = client.post("/v1/recordings", data=form, files=files, headers={"Idempotency-Key": "x y"})
    assert bad.status_code == 422


def test_unknown_form_fields_and_bad_ids_are_rejected(client, store):
    assert upload(client, community_id="../c1").status_code == 422
    assert upload(client, surprise="yes").status_code == 422
    assert len(store.objects) == 0


def test_the_audio_is_deleted_again_if_saving_the_records_fails(client, engine, store, monkeypatch):
    def broken(self, recording, idempotency_key=None):
        raise RuntimeError("database down")

    monkeypatch.setattr(RecordingRepository, "create", broken)
    assert (
        TestClient(app, raise_server_exceptions=False)
        .post(
            "/v1/recordings",
            data={"language": "ta", "community_id": "c1", "consent_id": "consent-1"},
            files={"file": ("a.wav", wav_bytes(), "audio/wav")},
            headers={"Idempotency-Key": "key-00000009"},
        )
        .status_code
        == 500
    )
    assert len(store.objects) == 0


def test_an_oversize_body_is_refused_from_its_declared_length(client, store):
    huge = wav_bytes(1.0, 1_500_000)  # about 3 MB against a 1 MB limit
    assert upload(client, huge).status_code == 413
    assert len(store.objects) == 0


def test_job_status_is_visible_to_the_uploader_and_a_reviewer_of_the_community(client):
    job_id = upload(client).json()["job_id"]
    body = client.get(f"/v1/jobs/{job_id}").json()
    assert (body["status"], body["stage"], body["error"]) == ("queued", None, None)
    act_as(person(Role.REVIEWER, user_id="rev"))
    assert client.get(f"/v1/jobs/{job_id}").status_code == 200


def test_hidden_and_missing_jobs_and_recordings_look_identical(client):
    ids = upload(client).json()
    missing_job = client.get("/v1/jobs/nope")
    missing_rec = client.get("/v1/recordings/nope")
    for principal in (
        person(user_id="other-member"),
        person(Role.REVIEWER, user_id="r", communities=("c2",)),
        person(Role.ADMIN, user_id="a", communities=()),
    ):
        act_as(principal)
        hidden_job = client.get(f"/v1/jobs/{ids['job_id']}")
        hidden_rec = client.get(f"/v1/recordings/{ids['recording_id']}")
        assert (hidden_job.status_code, hidden_job.json()) == (404, missing_job.json())
        assert (hidden_rec.status_code, hidden_rec.json()) == (404, missing_rec.json())


def test_recording_detail_has_no_transcript_until_ingestion_finishes(client):
    recording_id = upload(client).json()["recording_id"]
    body = client.get(f"/v1/recordings/{recording_id}").json()
    assert (body["status"], body["transcript"], body["translation"]) == ("draft", None, None)
    assert "audio_key" not in body
