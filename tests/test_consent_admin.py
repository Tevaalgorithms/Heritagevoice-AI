import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.api.auth import current_principal, get_session_factory
from app.api.main import app
from app.api.recordings import get_audio_store
from app.audio import AudioRules
from app.db.repositories import (
    ConsentRepository,
    JobRepository,
    RecordingRepository,
    TranscriptRepository,
)
from app.db.session import session_scope
from app.db.tables import AuditLogRow, Base, TranscriptVersionRow
from app.fakes import FakeAudioStore, FakeTranscriber
from app.ingest import IngestDeps, ingest_handler
from app.models.job import JobStatus
from app.models.records import RecordingStatus, Right, VersionStatus
from app.models.transcript import Segment
from app.security.roles import Role
from app.uploads import UploadDeps, UploadRequest, accept_upload
from app.worker import process_next
from tests.helpers import consent, person, wav_bytes

ADMIN = person(Role.ADMIN, user_id="admin-1", communities=())
RULES = AudioRules(max_bytes=5_000_000, max_seconds=600.0, languages=frozenset({"ta", "en"}))
GOOD = [Segment(segment_id="s1", start_s=0.0, end_s=0.5, text="vanakkam")]


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'consent.db'}")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def client(engine):
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    app.dependency_overrides[get_audio_store] = FakeAudioStore
    app.dependency_overrides[current_principal] = lambda: ADMIN
    yield TestClient(app)
    app.dependency_overrides.clear()


def act_as(principal):
    app.dependency_overrides[current_principal] = lambda: principal


def create(client, **overrides):
    body = {"community_id": "c1", "rights": ["ai_processing", "translation"], **overrides}
    return client.post("/admin/consents", json=body)


def audit_rows(engine):
    with Session(engine) as session:
        return list(session.scalars(select(AuditLogRow).order_by(AuditLogRow.id)))


def upload(engine, consent_id):
    deps = UploadDeps(lambda: session_scope(engine), FakeAudioStore(), RULES)
    request = UploadRequest(person(), "c1", "ta", consent_id, "key-00000001", wav_bytes(1.0))
    return accept_upload(request, deps)


def test_an_admin_creates_a_consent_and_it_is_audit_logged(client, engine):
    response = create(client, policy_version="v2")
    body = response.json()
    assert response.status_code == 201
    assert body["rights"] == ["ai_processing", "translation"]
    assert (body["community_id"], body["policy_version"], body["revoked"]) == ("c1", "v2", False)
    with Session(engine) as session:
        stored = ConsentRepository(session).get(body["id"])
    assert stored.rights == {Right.AI_PROCESSING, Right.TRANSLATION}
    (entry,) = audit_rows(engine)
    assert (entry.actor_sub, entry.action, entry.target) == (
        "admin-1",
        "consent:create",
        f"consent:{body['id']}",
    )


@pytest.mark.parametrize("role", [Role.MEMBER, Role.REVIEWER])
def test_only_admins_manage_consents(client, role):
    act_as(person(role))
    assert create(client).status_code == 403
    assert client.get("/admin/consents/x").status_code == 403
    assert client.post("/admin/consents/x/revoke").status_code == 403


@pytest.mark.parametrize(
    "overrides",
    [
        {"rights": []},
        {"rights": ["time_travel"]},
        {"community_id": "../c1"},
        {"policy_version": "bad version!"},
        {"surprise": True},
    ],
    ids=["no-rights", "unknown-right", "bad-community", "bad-policy", "extra-field"],
)
def test_invalid_consents_are_rejected(client, engine, overrides):
    assert create(client, **overrides).status_code == 422
    assert audit_rows(engine) == []


def test_a_consent_can_be_read_and_unknown_ones_are_404(client):
    consent_id = create(client).json()["id"]
    assert client.get(f"/admin/consents/{consent_id}").json()["id"] == consent_id
    assert client.get("/admin/consents/nope").status_code == 404
    assert client.get("/admin/consents/bad%20id").status_code == 422


def test_a_created_consent_can_be_used_for_an_upload(client, engine):
    consent_id = create(client).json()["id"]
    assert upload(engine, consent_id).created


def seed(engine, consent_id="consent-1", rights=tuple(Right)):
    with session_scope(engine) as session:
        ConsentRepository(session).add(consent(consent_id, "c1", rights=rights))


def test_revoking_a_consent_revokes_its_recordings_and_stops_their_jobs(client, engine):
    seed(engine, "consent-1")
    seed(engine, "consent-2")
    mine = upload(engine, "consent-1")
    other = upload_with_key(engine, "consent-2", "key-00000002")
    response = client.post("/admin/consents/consent-1/revoke")
    assert response.json() == {
        "consent_id": "consent-1",
        "recordings_revoked": 1,
        "jobs_stopped": 1,
    }
    with Session(engine) as session:
        recordings, jobs = RecordingRepository(session), JobRepository(session)
        assert recordings.get(mine.recording_id).status == RecordingStatus.REVOKED
        assert (jobs.get(mine.job_id).status, jobs.get(mine.job_id).error) == (
            JobStatus.FAILED,
            "consent",
        )
        assert recordings.get(other.recording_id).status == RecordingStatus.DRAFT
        assert jobs.get(other.job_id).status == JobStatus.QUEUED
        assert ConsentRepository(session).get("consent-1").revoked
    assert audit_rows(engine)[-1].action == "consent:revoke"


def upload_with_key(engine, consent_id, key):
    deps = UploadDeps(lambda: session_scope(engine), FakeAudioStore(), RULES)
    request = UploadRequest(person(), "c1", "ta", consent_id, key, wav_bytes(1.0))
    return accept_upload(request, deps)


def test_revoking_twice_is_safe_and_unknown_consents_are_404(client, engine):
    seed(engine)
    upload(engine, "consent-1")
    first = client.post("/admin/consents/consent-1/revoke").json()
    second = client.post("/admin/consents/consent-1/revoke").json()
    assert (first["recordings_revoked"], second["jobs_stopped"]) == (1, 0)
    assert client.post("/admin/consents/nope/revoke").status_code == 404


def test_a_revoked_consent_blocks_new_uploads_and_the_worker_never_runs_the_job(client, engine):
    seed(engine)
    accepted = upload(engine, "consent-1")
    client.post("/admin/consents/consent-1/revoke")
    with pytest.raises(PermissionError):
        upload_with_key(engine, "consent-1", "key-00000003")
    deps = IngestDeps(lambda: session_scope(engine), FakeTranscriber(GOOD))
    assert not process_next(engine, {"ingest_recording": ingest_handler(deps)})
    with Session(engine) as session:
        assert TranscriptRepository(session).latest(accepted.recording_id) is None


class RevokingTranscriber(FakeTranscriber):
    """Revokes the consent while the speech service is 'working'."""

    def __init__(self, engine):
        super().__init__(GOOD)
        self._engine = engine

    def transcribe(self, audio_key, language):
        with session_scope(self._engine) as session:
            ConsentRepository(session).revoke("consent-1")
        return super().transcribe(audio_key, language)


def test_consent_revoked_while_a_job_runs_discards_the_result(engine):
    seed(engine)
    accepted = upload(engine, "consent-1")
    deps = IngestDeps(lambda: session_scope(engine), RevokingTranscriber(engine))
    process_next(engine, {"ingest_recording": ingest_handler(deps)})
    with Session(engine) as session:
        job = JobRepository(session).get(accepted.job_id)
        assert (job.status, job.error) == (JobStatus.FAILED, "consent")
        assert TranscriptRepository(session).latest(accepted.recording_id) is None


def test_a_revoked_recording_never_yields_approved_segments(engine):
    seed(engine)
    accepted = upload(engine, "consent-1")
    with session_scope(engine) as session:
        transcripts = TranscriptRepository(session)
        transcripts.save_draft(accepted.recording_id, GOOD, "system")
        session.execute(
            text("update transcript_version set status = :s"), {"s": VersionStatus.APPROVED}
        )
        assert transcripts.approved_segments(accepted.recording_id) == GOOD
        RecordingRepository(session).set_status(accepted.recording_id, RecordingStatus.REVOKED)
        assert transcripts.approved_segments(accepted.recording_id) == []
    with Session(engine) as session:
        assert session.scalars(select(TranscriptVersionRow)).first().status == "approved"


def test_an_admin_can_revoke_one_recording_with_a_reason(client, engine):
    seed(engine)
    accepted = upload(engine, "consent-1")
    body = {"policy_version": "v3", "reason": "Speaker asked for removal"}
    response = client.post(f"/v1/recordings/{accepted.recording_id}/revoke", json=body)
    assert response.json() == {
        "recording_id": accepted.recording_id,
        "status": "revoked",
        "jobs_stopped": 1,
    }
    entry = audit_rows(engine)[-1]
    assert (entry.action, entry.target) == (
        "recording:revoke",
        f"recording:{accepted.recording_id}",
    )
    assert entry.detail == "v3: Speaker asked for removal"
    with Session(engine) as session:
        assert not ConsentRepository(session).get("consent-1").revoked


@pytest.mark.parametrize("role", [Role.MEMBER, Role.REVIEWER])
def test_only_admins_revoke_recordings(client, engine, role):
    seed(engine)
    accepted = upload(engine, "consent-1")
    act_as(person(role))
    body = {"policy_version": "v1", "reason": "x"}
    assert (
        client.post(f"/v1/recordings/{accepted.recording_id}/revoke", json=body).status_code == 403
    )


@pytest.mark.parametrize(
    "body",
    [
        {"policy_version": "v1"},
        {"policy_version": "v1", "reason": ""},
        {"policy_version": "v1", "reason": "x" * 151},
        {"policy_version": "bad version", "reason": "x"},
        {"policy_version": "v1", "reason": "x", "extra": 1},
    ],
)
def test_invalid_revocations_are_rejected(client, body):
    assert client.post("/v1/recordings/any/revoke", json=body).status_code == 422


def test_revoking_an_unknown_recording_is_404(client):
    body = {"policy_version": "v1", "reason": "x"}
    assert client.post("/v1/recordings/nope/revoke", json=body).status_code == 404
