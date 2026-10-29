import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.auth import current_principal, get_session_factory
from app.api.main import app
from app.audio import AudioRules
from app.db.repositories import (
    ConsentRepository,
    RecordingRepository,
    ReviewDecisionRepository,
    TranscriptRepository,
    VersionRepository,
)
from app.db.session import session_scope
from app.db.tables import Base
from app.fakes import FakeAudioStore, FakeTranscriber, FakeTranslator
from app.ingest import IngestDeps, ingest_handler
from app.models.records import RecordingStatus, Right, Subject, VersionStatus
from app.models.transcript import Segment
from app.security.roles import Role
from app.uploads import UploadDeps, UploadRequest, accept_upload
from app.worker import process_next
from tests.helpers import consent, person, wav_bytes

RULES = AudioRules(max_bytes=5_000_000, max_seconds=600.0, languages=frozenset({"ta", "en"}))
SEGMENTS = [
    Segment(segment_id="s1", start_s=0.0, end_s=0.5, text="vanakkam"),
    Segment(segment_id="s2", start_s=0.5, end_s=0.9, text="nandri"),
]
OWNER = person(Role.MEMBER, user_id="owner")
REVIEWER = person(Role.REVIEWER, user_id="rev")
OTHER_REVIEWER = person(Role.REVIEWER, user_id="rev2", communities=("c2",))
OTHER_MEMBER = person(Role.MEMBER, user_id="stranger")
ADMIN = person(Role.ADMIN, user_id="admin", communities=())


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'review.db'}")
    Base.metadata.create_all(engine)
    with session_scope(engine) as session:
        repo = ConsentRepository(session)
        repo.add(consent("consent-1", "c1"))
        repo.add(consent("consent-noindex", "c1", rights=[Right.AI_PROCESSING, Right.TRANSLATION]))
    return engine


@pytest.fixture
def client(engine):
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    app.dependency_overrides[current_principal] = lambda: REVIEWER
    yield TestClient(app)
    app.dependency_overrides.clear()


def act_as(principal):
    app.dependency_overrides[current_principal] = lambda: principal


def reviewable(engine, uploader=OWNER, consent_id="consent-1", key="key-00000001"):
    """A recording with draft transcript and translation, waiting for review."""
    deps = UploadDeps(lambda: session_scope(engine), FakeAudioStore(), RULES)
    request = UploadRequest(uploader, "c1", "ta", consent_id, key, wav_bytes(1.0))
    accepted = accept_upload(request, deps)
    ingest = IngestDeps(lambda: session_scope(engine), FakeTranscriber(SEGMENTS), FakeTranslator())
    process_next(engine, {"ingest_recording": ingest_handler(ingest)})
    return accepted.recording_id


def url(recording_id, action):
    return f"/v1/recordings/{recording_id}/{action}"


def decision(kind="transcript", version=1, approved=True, **extra):
    return {"kind": kind, "expected_version": version, "approved": approved, **extra}


def edit(kind="transcript", version=1, text="corrected", segment="s1"):
    return {
        "kind": kind,
        "expected_version": version,
        "edits": [{"segment_id": segment, "text": text}],
    }


def version(engine, recording_id, kind):
    with Session(engine) as session:
        return VersionRepository(session).latest(recording_id, kind)


def status(engine, recording_id):
    with Session(engine) as session:
        return RecordingRepository(session).get(recording_id).status


def test_each_user_sees_only_the_recordings_they_may(client, engine):
    reviewable(engine)
    expected = {OWNER: 1, REVIEWER: 1, OTHER_MEMBER: 0, OTHER_REVIEWER: 0, ADMIN: 0}
    for principal, count in expected.items():
        act_as(principal)
        assert len(client.get("/v1/recordings").json()) == count


def test_an_edit_creates_the_next_draft_and_keeps_ids_and_timing(client, engine):
    recording_id = reviewable(engine)
    act_as(OWNER)
    response = client.patch(url(recording_id, "draft"), json=edit(text="vanakkam!"))
    assert response.json() == {"kind": "transcript", "version": 2, "status": "draft"}
    latest = version(engine, recording_id, Subject.TRANSCRIPT)
    assert [(s.segment_id, s.start_s, s.end_s, s.text) for s in latest.segments] == [
        ("s1", 0.0, 0.5, "vanakkam!"),
        ("s2", 0.5, 0.9, "nandri"),
    ]
    with Session(engine) as session:
        first = [r for r in VersionRepository(session)._rows(recording_id, Subject.TRANSCRIPT)]
    assert {r.version: r.status for r in first} == {1: "superseded", 2: "draft"}


def test_an_edit_against_an_older_version_is_refused_as_stale(client, engine):
    recording_id = reviewable(engine)
    act_as(OWNER)
    assert client.patch(url(recording_id, "draft"), json=edit()).status_code == 200
    stale = client.patch(url(recording_id, "draft"), json=edit(version=1, text="late"))
    assert (stale.status_code, stale.json()["detail"]["code"]) == (409, "stale_version")
    assert version(engine, recording_id, Subject.TRANSCRIPT).version == 2


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "transcript", "expected_version": 1, "edits": []},
        {"kind": "assertion", "expected_version": 1, "edits": [{"segment_id": "s1", "text": "x"}]},
        {"kind": "transcript", "expected_version": 0, "edits": [{"segment_id": "s1", "text": "x"}]},
        {"kind": "transcript", "expected_version": 1, "edits": [{"segment_id": "s1", "text": ""}]},
        {
            "kind": "transcript",
            "expected_version": 1,
            "edits": [{"segment_id": "s1", "text": "x"}],
            "by": "me",
        },
    ],
    ids=["no-edits", "bad-kind", "bad-version", "empty-text", "extra-field"],
)
def test_malformed_edits_are_rejected(client, engine, body):
    recording_id = reviewable(engine)
    act_as(OWNER)
    assert client.patch(url(recording_id, "draft"), json=body).status_code == 422


def test_editing_an_unknown_segment_is_422_and_changes_nothing(client, engine):
    recording_id = reviewable(engine)
    act_as(OWNER)
    response = client.patch(url(recording_id, "draft"), json=edit(segment="s99"))
    assert (response.status_code, response.json()["detail"]["code"]) == (422, "unknown_segment")
    assert version(engine, recording_id, Subject.TRANSCRIPT).version == 1


def test_hidden_recordings_cannot_be_edited_reviewed_or_published(client, engine):
    recording_id = reviewable(engine)
    missing = client.patch(url("nope", "draft"), json=edit())
    for principal in (OTHER_MEMBER, OTHER_REVIEWER, ADMIN):
        act_as(principal)
        for response in (
            client.patch(url(recording_id, "draft"), json=edit()),
            client.post(url(recording_id, "review"), json=decision()),
            client.post(url(recording_id, "publish")),
        ):
            assert (response.status_code, response.json()) == (404, missing.json())


def test_members_cannot_approve_and_forged_reviewer_fields_are_ignored(client, engine):
    recording_id = reviewable(engine)
    act_as(OWNER)
    assert client.post(url(recording_id, "review"), json=decision()).status_code == 403
    forged = decision(reviewer_id="rev", role="reviewer")
    assert client.post(url(recording_id, "review"), json=forged).status_code == 422
    assert version(engine, recording_id, Subject.TRANSCRIPT).status == VersionStatus.DRAFT


def test_a_reviewer_cannot_approve_their_own_upload(client, engine):
    recording_id = reviewable(engine, uploader=person(Role.REVIEWER, user_id="rev"))
    act_as(REVIEWER)
    response = client.post(url(recording_id, "review"), json=decision())
    assert response.status_code == 403
    assert client.post(url(recording_id, "publish")).status_code == 403


def test_an_approval_records_the_reviewer_from_the_server_identity(client, engine):
    recording_id = reviewable(engine)
    response = client.post(url(recording_id, "review"), json=decision(note="checked with elder"))
    assert response.json() == {"kind": "transcript", "version": 1, "status": "approved"}
    with Session(engine) as session:
        (saved,) = ReviewDecisionRepository(session).for_recording(recording_id)
    assert (saved.reviewer_id, saved.subject, saved.approved, saved.note) == (
        "rev",
        Subject.TRANSCRIPT,
        True,
        "checked with elder",
    )


def test_stale_repeated_and_rejected_decisions_are_refused(client, engine):
    recording_id = reviewable(engine)
    assert client.post(url(recording_id, "review"), json=decision(version=5)).status_code == 409
    assert client.post(url(recording_id, "review"), json=decision()).status_code == 200
    again = client.post(url(recording_id, "review"), json=decision())
    assert (again.status_code, again.json()["detail"]["code"]) == (409, "not_reviewable")


def test_a_rejected_draft_cannot_later_be_approved(client, engine):
    recording_id = reviewable(engine)
    rejected = client.post(url(recording_id, "review"), json=decision(approved=False))
    assert rejected.json()["status"] == "rejected"
    assert client.post(url(recording_id, "review"), json=decision()).status_code == 409


def test_transcript_and_translation_are_approved_independently(client, engine):
    recording_id = reviewable(engine)
    early = client.post(url(recording_id, "review"), json=decision("translation"))
    assert (early.status_code, early.json()["detail"]["code"]) == (409, "transcript_not_approved")
    client.post(url(recording_id, "review"), json=decision("transcript"))
    assert client.post(url(recording_id, "review"), json=decision("translation")).status_code == 200
    assert version(engine, recording_id, Subject.TRANSLATION).status == VersionStatus.APPROVED


def test_a_translation_of_an_older_transcript_cannot_be_approved(client, engine):
    recording_id = reviewable(engine)
    act_as(OWNER)
    client.patch(url(recording_id, "draft"), json=edit())  # transcript is now version 2
    act_as(REVIEWER)
    client.post(url(recording_id, "review"), json=decision("transcript", 2))
    stale = client.post(url(recording_id, "review"), json=decision("translation"))
    assert (stale.status_code, stale.json()["detail"]["code"]) == (409, "transcript_not_approved")


def test_publishing_needs_an_approved_transcript(client, engine):
    recording_id = reviewable(engine)
    refused = client.post(url(recording_id, "publish"))
    assert (refused.status_code, refused.json()["detail"]["code"]) == (
        409,
        "transcript_not_approved",
    )
    assert status(engine, recording_id) == RecordingStatus.REVIEW


def test_publishing_needs_indexing_consent(client, engine):
    recording_id = reviewable(engine, consent_id="consent-noindex")
    client.post(url(recording_id, "review"), json=decision())
    refused = client.post(url(recording_id, "publish"))
    assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "consent_denied")
    assert status(engine, recording_id) == RecordingStatus.REVIEW


def test_only_approved_current_content_becomes_searchable(client, engine):
    recording_id = reviewable(engine)
    with Session(engine) as session:
        assert TranscriptRepository(session).approved_segments(recording_id) == []  # pending
    client.post(url(recording_id, "review"), json=decision())
    assert client.post(url(recording_id, "publish")).json()["status"] == "published"
    assert client.post(url(recording_id, "publish")).status_code == 200  # safe to repeat
    with Session(engine) as session:
        assert len(TranscriptRepository(session).approved_segments(recording_id)) == 2


def test_a_correction_after_publishing_pulls_the_content_back_to_review(client, engine):
    recording_id = reviewable(engine)
    client.post(url(recording_id, "review"), json=decision())
    client.post(url(recording_id, "publish"))
    act_as(OWNER)
    assert client.patch(url(recording_id, "draft"), json=edit()).status_code == 200
    assert status(engine, recording_id) == RecordingStatus.REVIEW
    with Session(engine) as session:
        assert TranscriptRepository(session).approved_segments(recording_id) == []
    act_as(REVIEWER)
    assert client.post(url(recording_id, "publish")).status_code == 409


def test_revoked_recordings_cannot_be_reviewed_edited_or_published(client, engine):
    recording_id = reviewable(engine)
    client.post(url(recording_id, "review"), json=decision())
    with session_scope(engine) as session:
        RecordingRepository(session).set_status(recording_id, RecordingStatus.REVOKED)
    for response in (
        client.post(url(recording_id, "publish")),
        client.post(url(recording_id, "review"), json=decision("translation")),
        client.patch(url(recording_id, "draft"), json=edit(version=1)),
    ):
        assert (response.status_code, response.json()["detail"]["code"]) == (409, "not_reviewable")
    with Session(engine) as session:
        assert TranscriptRepository(session).approved_segments(recording_id) == []


def test_recordings_still_in_ingestion_cannot_be_reviewed(client, engine):
    deps = UploadDeps(lambda: session_scope(engine), FakeAudioStore(), RULES)
    request = UploadRequest(OWNER, "c1", "ta", "consent-1", "key-00000009", wav_bytes(1.0))
    recording_id = accept_upload(request, deps).recording_id
    response = client.post(url(recording_id, "review"), json=decision())
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "not_reviewable")
