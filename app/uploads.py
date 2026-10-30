"""Accept an uploaded recording: check everything first, then store the audio and queue the job.

Order matters: replay check, then access and consent, then the cheap input checks, then the audio
itself. Nothing is stored or queued until every check has passed, and an unrelated failure after
storing removes the stored object again.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audio import AudioInfo, AudioRules, UploadError, check_language, validate_audio
from app.db.repositories import ConsentRepository, JobRepository, RecordingRepository
from app.models.records import HeritageKind, Recording, Right
from app.ports import AudioStore
from app.security.consent import ConsentDeniedError, require_right
from app.security.permissions import Principal, Resource, authorize
from app.security.roles import Action

SessionFactory = Callable[[], AbstractContextManager[Session]]
INGEST_KIND = "ingest_recording"


class AccessDeniedError(PermissionError):
    """The user may not upload to this community."""


@dataclass(frozen=True)
class UploadDeps:
    """What an upload needs: database sessions, audio storage and the rules."""

    sessions: SessionFactory
    store: AudioStore
    rules: AudioRules


@dataclass(frozen=True)
class UploadRequest:
    """Everything about one upload request, with the audio bytes."""

    principal: Principal
    community_id: str
    language: str
    consent_id: str
    idempotency_key: str
    data: bytes
    heritage_kind: HeritageKind = HeritageKind.STORY


@dataclass(frozen=True)
class Accepted:
    """The outcome of an accepted upload."""

    recording_id: str
    job_id: str
    created: bool


def _replay(request: UploadRequest, deps: UploadDeps) -> Accepted | None:
    with deps.sessions() as session:
        existing = RecordingRepository(session).find_by_idempotency(
            request.principal.user_id, request.idempotency_key
        )
        job = None if existing is None else JobRepository(session).by_recording(existing.id)
    return None if existing is None or job is None else Accepted(existing.id, job.id, False)


def _check_access(request: UploadRequest) -> None:
    resource = Resource(request.community_id, request.principal.user_id)
    if not authorize(request.principal, Action.RECORDING_UPLOAD, resource).allowed:
        raise AccessDeniedError("Not permitted to upload to this community")


def _check_consent(request: UploadRequest, deps: UploadDeps) -> None:
    with deps.sessions() as session:
        consent = ConsentRepository(session).get(request.consent_id)
    if consent is not None and consent.community_id != request.community_id:
        consent = None  # a consent from another community is the same as no consent
    require_right(consent, Right.AI_PROCESSING)
    require_right(consent, Right.TRANSLATION)


def _storage_key(community_id: str, recording_id: str) -> str:
    return f"recordings/{community_id}/{recording_id}/original"


def _new_recording(request: UploadRequest, info: AudioInfo, key: str) -> Recording:
    return Recording(
        id=key.split("/")[2],
        community_id=request.community_id,
        uploader_id=request.principal.user_id,
        language=request.language,
        consent_id=request.consent_id,
        heritage_kind=request.heritage_kind,
        audio_key=key,
        content_type=info.content_type,
        size_bytes=info.size_bytes,
        duration_s=info.duration_s,
    )


def _persist(recording: Recording, idempotency_key: str, deps: UploadDeps) -> Accepted:
    job_id = uuid4().hex
    with deps.sessions() as session:
        RecordingRepository(session).create(recording, idempotency_key)
        JobRepository(session).create(job_id, INGEST_KIND, recording.id)
    return Accepted(recording.id, job_id, True)


def _store_and_queue(request: UploadRequest, info: AudioInfo, deps: UploadDeps) -> Accepted:
    key = _storage_key(request.community_id, uuid4().hex)
    deps.store.put(key, request.data, info.content_type)
    try:
        return _persist(_new_recording(request, info, key), request.idempotency_key, deps)
    except IntegrityError:  # a concurrent request with the same idempotency key won
        deps.store.delete(key)
        replay = _replay(request, deps)
        if replay is None:
            raise
        return replay
    except Exception:
        deps.store.delete(key)
        raise


def accept_upload(request: UploadRequest, deps: UploadDeps) -> Accepted:
    replay = _replay(request, deps)
    if replay is not None:
        return replay
    _check_access(request)
    _check_consent(request, deps)
    check_language(request.language, deps.rules)
    info = validate_audio(request.data, deps.rules)
    return _store_and_queue(request, info, deps)


__all__ = [
    "INGEST_KIND",
    "AccessDeniedError",
    "Accepted",
    "ConsentDeniedError",
    "UploadDeps",
    "UploadError",
    "UploadRequest",
    "accept_upload",
]
