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
from app.db.repositories import RecordingRepository
from app.models.records import Recording, Subject
from app.review import DecisionInput, EditInput, ReviewError, decide, edit_draft, publish
from app.security.consent import ConsentDeniedError
from app.security.permissions import Principal, Resource, authorize
from app.security.roles import Action, Role

router = APIRouter(prefix="/v1", tags=["review"])
Kind = Literal["transcript", "translation"]
SEGMENT_ID = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
MAX_EDITS = 500


class SegmentEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_id: Annotated[str, SEGMENT_ID]
    text: Annotated[str, Field(min_length=1, max_length=2000)]


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Kind
    expected_version: Annotated[int, Field(ge=1)]
    edits: Annotated[list[SegmentEdit], Field(min_length=1, max_length=MAX_EDITS)]


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Kind
    expected_version: Annotated[int, Field(ge=1)]
    approved: bool
    note: Annotated[str | None, Field(max_length=500)] = None


class VersionResult(BaseModel):
    kind: str
    version: int
    status: str


class PublishResult(BaseModel):
    recording_id: str
    status: str


class RecordingSummary(BaseModel):
    id: str
    community_id: str
    language: str
    heritage_kind: str
    status: str
    duration_s: float | None


def _error(error: Exception) -> HTTPException:
    if isinstance(error, ReviewError):
        return HTTPException(status_code=error.status_code, detail={"code": error.code})
    return HTTPException(status_code=403, detail={"code": "consent_denied"})


def _allowed_recording(
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
    """Members see their own recordings, reviewers those of their communities, admins none."""
    if principal.role is Role.ADMIN:
        return []
    owner = principal.user_id if principal.role is Role.MEMBER else None
    with factory() as session:
        found = RecordingRepository(session).list_for(principal.communities, owner)
    return [
        RecordingSummary(
            id=r.id,
            community_id=r.community_id,
            language=r.language,
            heritage_kind=r.heritage_kind,
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
        recording = _allowed_recording(session, principal, recording_id, Action.DRAFT_EDIT)
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
        recording = _allowed_recording(session, principal, recording_id, Action.REVIEW_APPROVE)
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
        recording = _allowed_recording(session, principal, recording_id, Action.REVIEW_APPROVE)
        try:
            status = publish(session, recording)
        except (ReviewError, ConsentDeniedError) as error:
            raise _error(error) from error
    return PublishResult(recording_id=recording_id, status=status)
