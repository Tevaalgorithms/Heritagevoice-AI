"""Recording endpoints: upload, job status and recording detail.

Every endpoint authenticates the user and resolves the community on the server. A recording or
job the user may not see answers exactly like one that does not exist.
"""

from dataclasses import dataclass
from pathlib import Path as FilePath
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Form,
    Header,
    HTTPException,
    Path,
    Request,
    Response,
    UploadFile,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.adapters.audio_store import LocalAudioStore, S3AudioStore
from app.api.admin import AdminContext, context_for
from app.api.auth import SessionFactory, current_principal, get_session_factory
from app.api.tracing import current_trace_id
from app.audio import AudioRules, UploadError
from app.config import Settings
from app.credits import credit_for
from app.db.repositories import (
    AuditEntry,
    AuditRepository,
    ConsentRepository,
    JobRepository,
    RecordingRepository,
    TranscriptRepository,
)
from app.discard import DiscardRefusedError, discard_recording
from app.models.credit import MAX_NAME, MAX_NOTE, Credit, SourceKind
from app.models.job import Job
from app.models.records import HeritageKind, Recording, Visibility
from app.models.transcript import Segment
from app.ports import AudioStore
from app.revocation import revoke_recording
from app.security.consent import ConsentDeniedError
from app.security.permissions import Principal, Resource, authorize
from app.security.roles import Action
from app.uploads import AccessDeniedError, UploadDeps, UploadRequest, accept_upload

router = APIRouter(prefix="/v1", tags=["recordings"])
BYTES_PER_MB = 1024 * 1024
HEADROOM = BYTES_PER_MB  # multipart framing around the file
NOT_FOUND = HTTPException(status_code=404, detail="Not found")
ID = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
PathId = Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")


def get_audio_store() -> AudioStore:
    settings = Settings()
    if settings.audio_bucket:
        return S3AudioStore(settings.audio_bucket, settings.audio_kms_key_id)
    if settings.audio_local_dir:
        return LocalAudioStore(FilePath(settings.audio_local_dir))
    raise HTTPException(status_code=503, detail="Audio storage is not configured")


def rules_from_settings(settings: Settings) -> AudioRules:
    return AudioRules(
        max_bytes=settings.max_audio_mb * BYTES_PER_MB,
        max_seconds=settings.max_audio_minutes * 60.0,
        languages=frozenset(settings.allowed_languages.split(",")),
    )


def get_upload_deps(
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
    store: Annotated[AudioStore, Depends(get_audio_store)],
) -> UploadDeps:
    return UploadDeps(factory, store, rules_from_settings(Settings()))


@dataclass(frozen=True)
class UploadContext:
    """Who is uploading and the dependencies the upload needs."""

    principal: Principal
    deps: UploadDeps
    idempotency_key: str


def upload_context(
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
    deps: Annotated[UploadDeps, Depends(get_upload_deps)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", pattern=r"^[A-Za-z0-9_-]{8,64}$")
    ],
) -> UploadContext:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > deps.rules.max_bytes + HEADROOM:
        raise HTTPException(status_code=413, detail={"code": "too_large"})
    return UploadContext(principal, deps, idempotency_key)


class UploadForm(BaseModel):
    """The multipart form for an upload: the audio and what it contains."""

    model_config = ConfigDict(extra="forbid")
    file: UploadFile
    language: Annotated[str, Field(pattern=r"^[a-z]{2,8}$")]
    community_id: Annotated[str, ID]
    consent_id: Annotated[str, ID]
    heritage_kind: HeritageKind = HeritageKind.STORY
    visibility: Visibility = Visibility.COMMUNITY
    credit_name: Annotated[str | None, Field(max_length=MAX_NAME)] = None
    source_kind: SourceKind | None = None
    source_note: Annotated[str | None, Field(max_length=MAX_NOTE)] = None


class UploadResponse(BaseModel):
    """The IDs of the new recording and its processing job."""

    recording_id: str
    job_id: str


class JobResponse(BaseModel):
    """The state of a processing job, with a safe error code if it failed."""

    job_id: str
    status: str
    stage: str | None
    error: str | None
    recording_id: str | None


class VersionView(BaseModel):
    """One draft or approved version of a transcript or translation."""

    version: int
    status: str
    segments: list[Segment]


class RevokeRequest(BaseModel):
    """Request body to withdraw a recording, with the policy version and reason."""

    model_config = ConfigDict(extra="forbid")
    policy_version: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,32}$")]
    reason: Annotated[str, Field(min_length=1, max_length=150)]


class RevokeResponse(BaseModel):
    """What revoking a recording changed."""

    recording_id: str
    status: str
    jobs_stopped: int


class RecordingResponse(BaseModel):
    """A recording with its latest transcript and translation."""

    id: str
    community_id: str
    language: str
    heritage_kind: str
    visibility: str
    status: str
    duration_s: float | None
    transcript: VersionView | None
    translation: VersionView | None
    added: str = ""
    # What the contributor entered, for the people who may open the recording. `credit_public` says
    # whether readers will see it: only while the consent includes the attribution right.
    credit: Credit | None = None
    credit_public: bool = False


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, UploadError):
        return HTTPException(status_code=error.status_code, detail={"code": error.code})
    if isinstance(error, ConsentDeniedError):
        return HTTPException(status_code=403, detail={"code": "consent_denied"})
    return HTTPException(status_code=403, detail={"code": "forbidden"})


@router.post("/recordings", status_code=201)
async def upload_recording(
    form: Annotated[UploadForm, Form()],
    ctx: Annotated[UploadContext, Depends(upload_context)],
    response: Response,
) -> UploadResponse:
    data = await form.file.read(ctx.deps.rules.max_bytes + 1)
    request = UploadRequest(
        ctx.principal,
        form.community_id,
        form.language,
        form.consent_id,
        ctx.idempotency_key,
        data,
        form.heritage_kind,
        form.visibility,
        form.credit_name,
        form.source_kind,
        form.source_note,
    )
    try:
        accepted = await run_in_threadpool(accept_upload, request, ctx.deps)
    except (UploadError, ConsentDeniedError, AccessDeniedError) as error:
        raise _http_error(error) from error
    response.status_code = 201 if accepted.created else 200
    return UploadResponse(recording_id=accepted.recording_id, job_id=accepted.job_id)


def viewable(session: Session, principal: Principal, recording_id: str | None) -> Recording:
    recording = RecordingRepository(session).get(recording_id or "")
    if recording is None:
        raise NOT_FOUND
    resource = Resource(recording.community_id, recording.uploader_id)
    if not authorize(principal, Action.RECORDING_VIEW, resource).allowed:
        raise NOT_FOUND
    return recording


def _job_response(job: Job) -> JobResponse:
    return JobResponse(
        job_id=job.id,
        status=job.status,
        stage=job.stage,
        error=job.error,
        recording_id=job.recording_id,
    )


RevokeCtx = Annotated[AdminContext, Depends(context_for(Action.RECORDING_REVOKE))]


@router.post("/recordings/{recording_id}/revoke")
def revoke_recording_endpoint(
    recording_id: Annotated[str, PathId], body: RevokeRequest, ctx: RevokeCtx
) -> RevokeResponse:
    """Withdraw one recording at once: no further processing, indexing or playback."""
    detail = f"{body.policy_version}: {body.reason}"
    with ctx.factory() as session:
        result = revoke_recording(session, recording_id)
        if result is None:
            raise NOT_FOUND
        entry = ctx.entry("recording:revoke", f"recording:{recording_id}", detail)
        AuditRepository(session).record(entry)
    return RevokeResponse(
        recording_id=recording_id, status="revoked", jobs_stopped=result.jobs_stopped
    )


@router.delete("/recordings/{recording_id}", status_code=204)
def discard_recording_endpoint(
    recording_id: Annotated[str, PathId],
    principal: Annotated[Principal, Depends(current_principal)],
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
    store: Annotated[AudioStore, Depends(get_audio_store)],
) -> Response:
    """Throw away your own recording that nobody has approved yet: the audio, the transcript and
    the translation are erased. A recording that was shared is withdrawn instead."""
    with factory() as session:
        recording = viewable(session, principal, recording_id)
        resource = Resource(recording.community_id, recording.uploader_id)
        if not authorize(principal, Action.RECORDING_DISCARD, resource).allowed:
            raise NOT_FOUND
        try:
            discard_recording(session, store, principal, recording_id)
        except DiscardRefusedError as error:
            raise HTTPException(status_code=error.status, detail={"code": error.code}) from error
        # The log says who did it and to which recording, never what was said.
        entry = AuditEntry(
            principal.user_id, "recording:discard", f"recording:{recording_id}", current_trace_id()
        )
        AuditRepository(session).record(entry)
    return Response(status_code=204)


@router.get("/jobs/{job_id}")
def get_job(
    job_id: Annotated[str, PathId],
    principal: Annotated[Principal, Depends(current_principal)],
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> JobResponse:
    with factory() as session:
        job = JobRepository(session).get(job_id)
        if job is None:
            raise NOT_FOUND
        viewable(session, principal, job.recording_id)
        return _job_response(job)


@router.get("/recordings/{recording_id}")
def get_recording(
    recording_id: Annotated[str, PathId],
    principal: Annotated[Principal, Depends(current_principal)],
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> RecordingResponse:
    with factory() as session:
        recording = viewable(session, principal, recording_id)
        transcripts = TranscriptRepository(session)
        transcript = transcripts.latest(recording.id)
        translation = transcripts.latest_translation(recording.id)
        consent = ConsentRepository(session).get(recording.consent_id)
        entered = Credit(
            name=recording.credit_name,
            source_kind=recording.source_kind,
            source_note=recording.source_note,
        )
        return RecordingResponse(
            id=recording.id,
            community_id=recording.community_id,
            language=recording.language,
            heritage_kind=recording.heritage_kind,
            visibility=recording.visibility,
            status=recording.status,
            duration_s=recording.duration_s,
            transcript=None if transcript is None else VersionView(**transcript.model_dump()),
            translation=None if translation is None else VersionView(**translation.model_dump()),
            added=recording.added,
            credit=None if entered.is_empty() else entered,
            credit_public=credit_for(recording, consent) is not None,
        )
