"""Report a recording: anyone who can read it can say it should not be shared, and an admin decides.

A visitor with no account can report a public recording; a signed-in person can also report what
their group shares. Reporting is limited (a few per hour) and says nothing about whether the
recording exists unless the reporter could already read it. The reporter's identity and note are
shown to admins only, never to the uploader. An admin either takes the recording down (the same
withdrawal as revoking it: search, playback and the graph stop at once) or keeps it. Every
decision is audit-logged by ID.
"""

from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.orm import Session

from app.api.admin import AdminContext, context_for
from app.api.auth import SessionFactory, current_principal, get_session_factory
from app.api.public import ANONYMOUS, visitor_key
from app.db.repositories import (
    AuditRepository,
    ChunkRepository,
    RecordingRepository,
    ReportRepository,
)
from app.models.index import ChunkKind
from app.models.records import (
    ItemReport,
    Recording,
    RecordingStatus,
    ReportReason,
    ReportStatus,
    Visibility,
)
from app.ratelimit import SlidingWindowLimiter
from app.revocation import revoke_recording
from app.security.permissions import Principal
from app.security.roles import Action

router = APIRouter(tags=["reports"])
RecordingId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
REPORTS_PER_HOUR = 5
NO_STORE = {"Cache-Control": "no-store"}
_LIMITER = SlidingWindowLimiter(REPORTS_PER_HOUR, 3600.0)
Admin = Annotated[AdminContext, Depends(context_for(Action.RECORDING_REVOKE))]


def get_limiter() -> SlidingWindowLimiter:
    return _LIMITER


class ReportRequest(BaseModel):
    """What the reporter says: which recording, why, and an optional note."""

    model_config = ConfigDict(extra="forbid")
    recording_id: RecordingId
    reason: ReportReason
    note: Note | None = None


class ReportReceipt(BaseModel):
    """Confirmation that the report was received."""

    id: str


class ReportView(BaseModel):
    """A report as an admin sees it, with enough of the recording to decide."""

    id: str
    recording_id: str
    reason: ReportReason
    note: str | None
    reporter: str
    heritage_kind: str
    language: str
    community: str
    recording_status: RecordingStatus
    opening: str
    reports_for_recording: int


class Decision(BaseModel):
    """What the admin decides."""

    model_config = ConfigDict(extra="forbid")
    action: Literal["take_down", "dismiss"]


def _throttle(limiter: SlidingWindowLimiter, key: str) -> None:
    if not limiter.allow(key):
        retry = str(limiter.retry_after(key))
        raise HTTPException(
            status_code=429, detail={"code": "rate_limited"}, headers={"Retry-After": retry}
        )


def _readable(recording: Recording | None, principal: Principal) -> bool:
    """Published, and shared openly or with a group the reporter belongs to."""
    if recording is None or recording.status != RecordingStatus.PUBLISHED:
        return False
    return (
        recording.visibility is Visibility.PUBLIC or recording.community_id in principal.communities
    )


def _record(
    factory: SessionFactory, principal: Principal, body: ReportRequest, reporter: str | None
) -> ReportReceipt:
    with factory() as session:
        if not _readable(RecordingRepository(session).get(body.recording_id), principal):
            raise HTTPException(status_code=404, detail="Not found")
        report = ItemReport(
            id=uuid4().hex,
            recording_id=body.recording_id,
            reason=body.reason,
            note=body.note or None,
            reporter=reporter,
        )
        ReportRepository(session).add(report)
    return ReportReceipt(id=report.id)


@router.post("/v1/public/report", status_code=201)
def report_as_visitor(
    body: ReportRequest,
    request: Request,
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
    limiter: Annotated[SlidingWindowLimiter, Depends(get_limiter)],
) -> ReportReceipt:
    _throttle(limiter, visitor_key(request))
    return _record(factory, ANONYMOUS, body, None)


@router.post("/v1/reports", status_code=201)
def report_as_member(
    body: ReportRequest,
    principal: Annotated[Principal, Depends(current_principal)],
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
    limiter: Annotated[SlidingWindowLimiter, Depends(get_limiter)],
) -> ReportReceipt:
    _throttle(limiter, principal.user_id)
    return _record(factory, principal, body, principal.user_id)


def _opening(session: Session, recording_id: str) -> str:
    chunk = ChunkRepository(session).openings([recording_id], ChunkKind.TRANSCRIPT)
    return chunk[recording_id].text[:300] if recording_id in chunk else ""


def _view(session: Session, report: ItemReport, counts: dict[str, int]) -> ReportView | None:
    recording = RecordingRepository(session).get(report.recording_id)
    if recording is None:
        return None
    return ReportView(
        id=report.id,
        recording_id=recording.id,
        reason=report.reason,
        note=report.note,
        reporter=report.reporter or "a visitor",
        heritage_kind=recording.heritage_kind,
        language=recording.language,
        community=recording.community_id,
        recording_status=recording.status,
        opening=_opening(session, recording.id),
        reports_for_recording=counts[recording.id],
    )


@router.get("/v1/admin/reports")
def list_reports(
    ctx: Admin, status: Annotated[ReportStatus, Query()] = ReportStatus.OPEN
) -> list[ReportView]:
    with ctx.factory() as session:
        found = ReportRepository(session).with_status(status)
        counts: dict[str, int] = {}
        for report in found:
            counts[report.recording_id] = counts.get(report.recording_id, 0) + 1
        views = (_view(session, report, counts) for report in found)
        return [view for view in views if view is not None]


def _decide(session: Session, ctx: AdminContext, report: ItemReport, action: str) -> ReportStatus:
    """Apply the decision to the recording and to every open report about it."""
    taking_down = action == "take_down"
    if taking_down:
        revoke_recording(session, report.recording_id)
    status = ReportStatus.TAKEN_DOWN if taking_down else ReportStatus.DISMISSED
    ReportRepository(session).resolve_for_recording(report.recording_id, status, ctx.admin.user_id)
    return status


@router.post("/v1/admin/reports/{report_id}/decision")
def decide_report(
    report_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")], body: Decision, ctx: Admin
) -> dict[str, str]:
    with ctx.factory() as session:
        report = ReportRepository(session).get(report_id)
        if report is None or report.status is not ReportStatus.OPEN:
            raise HTTPException(status_code=404, detail="Not found")
        status = _decide(session, ctx, report, body.action)
        AuditRepository(session).record(ctx.entry(f"report:{status.value}", f"report:{report_id}"))
    return {"id": report_id, "status": status.value}
