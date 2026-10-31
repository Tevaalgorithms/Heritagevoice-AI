"""Review endpoints: list recordings, edit drafts, approve or reject, publish.

A recording the user cannot see answers 404, exactly like a missing one. Seeing it but lacking the
right to act on it answers 403. The reviewer's identity always comes from the server-side
principal, never from the request.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.auth import SessionFactory, current_principal, get_session_factory
from app.api.recordings import PathId, viewable
from app.api.tracing import current_trace_id
from app.db.repositories import AuditEntry, AuditRepository, RecordingRepository
from app.models.records import Recording, Subject, Visibility
from app.review import DecisionInput, EditInput, ReviewError, decide, edit_draft, publish
from app.security.consent import ConsentDeniedError
from app.security.permissions import Principal, Resource, authorize
from app.security.roles import Action, Role
from app.sharing import change_visibility

router = APIRouter(prefix="/v1", tags=["review"])
Kind = Literal["transcript", "translation"]
SEGMENT_ID = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
MAX_EDITS = 500


class SegmentEdit(BaseModel):
    """A corrected text for one segment."""

    model_config = ConfigDict(extra="forbid")
    segment_id: Annotated[str, SEGMENT_ID]
    text: Annotated[str, Field(min_length=1, max_length=2000)]


class EditRequest(BaseModel):
    """Request body to edit a draft, guarded by the version the editor saw."""

    model_config = ConfigDict(extra="forbid")
    kind: Kind
    expected_version: Annotated[int, Field(ge=1)]
    edits: Annotated[list[SegmentEdit], Field(min_length=1, max_length=MAX_EDITS)]


class DecisionRequest(BaseModel):
    """Request body to approve or reject a version, guarded by its version."""

    model_config = ConfigDict(extra="forbid")
    kind: Kind
    expected_version: Annotated[int, Field(ge=1)]
    approved: bool
    note: Annotated[str | None, Field(max_length=500)] = None


class VersionResult(BaseModel):
    """The new version created or decided by a review action."""

    kind: str
    version: int
    status: str


class PublishResult(BaseModel):
    """The recording's status after a publish attempt."""

    recording_id: str
    status: str


class RecordingSummary(BaseModel):
    """A recording as listed for reviewers."""

    id: str
    community_id: str
    language: str
    heritage_kind: str
    visibility: str
    status: str
    duration_s: float | None


def _error(error: Exception) -> HTTPException:
    if isinstance(error, ReviewError):
        return HTTPException(status_code=error.status_code, detail={"code": error.code})
    return HTTPException(status_code=403, detail={"code": "consent_denied"})


def allowed_recording(
    session: Session, principal: Principal, recording_id: str, action: Action
) -> Recording:
    recording = viewable(session, principal, recording_id)
    if not authorize(
        principal, action, Resource(recording.community_id, recording.uploader_id)
    ).allowed:
        raise HTTPException(status_code=403, detail={"code": "forbidden"})
    return recording


Principal_ = Annotated[Principal, Depends(current_principal)]
Factory = Annotated[SessionFactory, Depends(get_session_factory)]


@router.get("/recordings")
def list_recordings(principal: Principal_, factory: Factory) -> list[RecordingSummary]:
    """Members see their own recordings, reviewers those of their communities, admins every one."""
    owner = principal.user_id if principal.role is Role.MEMBER else None
    with factory() as session:
        repository = RecordingRepository(session)
        if principal.role is Role.ADMIN:
            found = repository.list_all()
        else:
            found = repository.list_for(principal.communities, owner)
    return [
        RecordingSummary(
            id=r.id,
            community_id=r.community_id,
            language=r.language,
            heritage_kind=r.heritage_kind,
            visibility=r.visibility,
            status=r.status,
            duration_s=r.duration_s,
        )
        for r in found
    ]


@router.patch("/recordings/{recording_id}/draft")
def edit_recording_draft(
    recording_id: Annotated[str, PathId], body: EditRequest, principal: Principal_, factory: Factory
) -> VersionResult:
    edits = {e.segment_id: e.text for e in body.edits}
    request = EditInput(Subject(body.kind), body.expected_version, edits, principal.user_id)
    with factory() as session:
        recording = allowed_recording(session, principal, recording_id, Action.DRAFT_EDIT)
        try:
            saved = edit_draft(session, recording, request)
        except ReviewError as error:
            raise _error(error) from error
    return VersionResult(kind=saved.kind, version=saved.version, status=saved.status)


@router.post("/recordings/{recording_id}/review")
def review_recording(
    recording_id: Annotated[str, PathId],
    body: DecisionRequest,
    principal: Principal_,
    factory: Factory,
) -> VersionResult:
    request = DecisionInput(Subject(body.kind), body.expected_version, body.approved, body.note)
    with factory() as session:
        recording = allowed_recording(session, principal, recording_id, Action.REVIEW_APPROVE)
        try:
            saved = decide(session, recording, request, principal.user_id)
        except ReviewError as error:
            raise _error(error) from error
    return VersionResult(kind=saved.kind, version=saved.version, status=saved.status)


@router.post("/recordings/{recording_id}/publish")
def publish_recording_endpoint(
    recording_id: Annotated[str, PathId], principal: Principal_, factory: Factory
) -> PublishResult:
    with factory() as session:
        recording = allowed_recording(session, principal, recording_id, Action.REVIEW_APPROVE)
        try:
            status = publish(session, recording)
        except (ReviewError, ConsentDeniedError) as error:
            raise _error(error) from error
    return PublishResult(recording_id=recording_id, status=status)


class VisibilityRequest(BaseModel):
    """Request body to change who may read a recording."""

    model_config = ConfigDict(extra="forbid")
    visibility: Visibility


class VisibilityResult(BaseModel):
    """The recording's visibility after the change."""

    recording_id: str
    visibility: str


@router.put("/recordings/{recording_id}/visibility")
def set_visibility_endpoint(
    recording_id: Annotated[str, PathId],
    body: VisibilityRequest,
    principal: Principal_,
    factory: Factory,
) -> VisibilityResult:
    """Admin only. Public needs the community's public-sharing consent; the change is audited."""
    with factory() as session:
        recording = allowed_recording(session, principal, recording_id, Action.VISIBILITY_MANAGE)
        try:
            change_visibility(session, recording, body.visibility)
        except ConsentDeniedError as error:
            raise _error(error) from error
        entry = AuditEntry(
            principal.user_id,
            "recording:visibility",
            f"recording:{recording_id}",
            current_trace_id(),
            body.visibility.value,
        )
        AuditRepository(session).record(entry)
    return VisibilityResult(recording_id=recording_id, visibility=body.visibility)
