"""Review the relationships a model proposed: approve, reject or correct each one.

Only an admin may review, and only for recordings they are allowed to review (the same rule as
transcripts, including that nobody approves their own upload). Approving is what lets a
relationship reach the knowledge graph; the graph is refreshed by a background job. Every
decision is audit-logged by ID, never with the content.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator
from sqlalchemy.orm import Session

from app.api.admin import AdminContext, context_for
from app.api.review import allowed_recording
from app.db.repositories import (
    AuditRepository,
    GraphAssertionRepository,
    JobRepository,
    VersionRepository,
)
from app.graph_extraction import EXTRACT_KIND
from app.index_sync import queue_graph_extraction, queue_graph_projection
from app.models.records import GraphAssertion, RecordingStatus, Relation, ReviewState, Subject
from app.models.transcript import Segment
from app.security.roles import Action

router = APIRouter(prefix="/v1/graph", tags=["graph"])
Ctx = Annotated[AdminContext, Depends(context_for(Action.REVIEW_APPROVE))]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
NOT_FOUND = HTTPException(status_code=404, detail="Not found")
LIST_LIMIT = 200


class AssertionView(BaseModel):
    """A proposed relationship with the words it came from, so a reviewer can check it."""

    id: str
    recording_id: str
    subject: str
    relation: Relation
    object: str
    asserted_by: str
    review_state: ReviewState
    confidence: float
    start_s: float | None
    end_s: float | None
    passage: str


class AssertionEdit(BaseModel):
    """Corrections to the words of a proposal. Anything left out stays as it was."""

    model_config = ConfigDict(extra="forbid")
    subject: Name | None = None
    relation: Relation | None = None
    object: Name | None = None

    @field_validator("relation")
    @classmethod
    def _not_a_support_link(cls, value: Relation | None) -> Relation | None:
        if value is Relation.SUPPORTED_BY:
            raise ValueError("support links are added by the system")
        return value


class DecisionRequest(BaseModel):
    """Approve or reject a proposal, optionally correcting it first."""

    model_config = ConfigDict(extra="forbid")
    approved: bool
    edit: AssertionEdit | None = None


class DecisionResult(BaseModel):
    """The new state of the proposal."""

    id: str
    review_state: ReviewState


def _problem(code: str, status: int) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code})


def _segment(session: Session, assertion: GraphAssertion) -> Segment | None:
    transcript = VersionRepository(session).approved(assertion.recording_id, Subject.TRANSCRIPT)
    if transcript is None:
        return None
    found = [s for s in transcript.segments if s.segment_id == assertion.supporting_segment_id]
    return found[0] if found else None


def passage_for(session: Session, assertion: GraphAssertion) -> str:
    """The words a proposal came from, or nothing if its transcript is no longer current."""
    segment = _segment(session, assertion)
    return segment.text if segment else ""


def _view(session: Session, assertion: GraphAssertion) -> AssertionView:
    segment = _segment(session, assertion)
    return AssertionView(
        id=assertion.id,
        recording_id=assertion.recording_id,
        subject=assertion.subject,
        relation=assertion.relation,
        object=assertion.object,
        asserted_by=assertion.asserted_by,
        review_state=assertion.review_state,
        confidence=assertion.confidence,
        start_s=segment.start_s if segment else None,
        end_s=segment.end_s if segment else None,
        passage=segment.text if segment else "",
    )


@router.get("/assertions")
def list_assertions(
    ctx: Ctx, state: Annotated[ReviewState, Query()] = ReviewState.PENDING
) -> list[AssertionView]:
    with ctx.factory() as session:
        found = GraphAssertionRepository(session).with_state(state, LIST_LIMIT)
        return [_view(session, assertion) for assertion in found]


def _current(session: Session, assertion: GraphAssertion) -> bool:
    transcript = VersionRepository(session).approved(assertion.recording_id, Subject.TRANSCRIPT)
    return transcript is not None and transcript.version == assertion.transcript_version


def _corrected(assertion: GraphAssertion, edit: AssertionEdit | None) -> GraphAssertion:
    """The assertion with the reviewer's corrections applied; its two ends must still differ."""
    changes = edit.model_dump(exclude_none=True) if edit else {}
    corrected = assertion.model_copy(update=changes)
    if corrected.subject.casefold() == corrected.object.casefold():
        raise _problem("invalid_edit", 422)
    return corrected


def _apply(
    session: Session, ctx: AdminContext, assertion_id: str, body: DecisionRequest
) -> ReviewState:
    repository = GraphAssertionRepository(session)
    assertion = repository.get(assertion_id)
    if assertion is None:
        raise NOT_FOUND
    allowed_recording(session, ctx.admin, assertion.recording_id, Action.REVIEW_APPROVE)
    if body.approved and not _current(session, assertion):
        raise _problem("stale_version", 409)
    corrected = _corrected(assertion, body.edit)
    repository.revise(assertion_id, corrected.subject, corrected.relation, corrected.object)
    state = ReviewState.APPROVED if body.approved else ReviewState.REJECTED
    repository.decide(assertion_id, state)
    AuditRepository(session).record(ctx.entry(f"graph:{state.value}", f"graph:{assertion_id}"))
    queue_graph_projection(session, assertion.recording_id)
    return state


@router.post("/assertions/{assertion_id}/decision")
def decide_assertion(
    assertion_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
    body: DecisionRequest,
    ctx: Ctx,
) -> DecisionResult:
    with ctx.factory() as session:
        state = _apply(session, ctx, assertion_id, body)
    return DecisionResult(id=assertion_id, review_state=state)


class FindResult(BaseModel):
    """Whether a new search for relationships was queued (false: one is already waiting)."""

    queued: bool


@router.post("/recordings/{recording_id}/find")
def find_relationships(
    recording_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")], ctx: Ctx
) -> FindResult:
    """Ask the model again for relationships in a published recording.

    The same background job as at publishing: it proposes new pending items and never changes a
    decision already made. Same access rule as reviewing; nothing is approved by this call.
    """
    with ctx.factory() as session:
        recording = allowed_recording(session, ctx.admin, recording_id, Action.REVIEW_APPROVE)
        if recording.status is not RecordingStatus.PUBLISHED:
            raise _problem("not_published", 409)
        if JobRepository(session).is_open(EXTRACT_KIND, recording_id):
            return FindResult(queued=False)
        queue_graph_extraction(session, recording_id)
        AuditRepository(session).record(ctx.entry("graph:find", f"recording:{recording_id}"))
    return FindResult(queued=True)
