"""Human review workflow: edit drafts, approve or reject versions, publish.

Rules (from the plan):
- Edits never overwrite: they create the next draft version, and an edit made against an older
  version is refused as stale.
- Transcript and translation are approved independently; a translation can only be approved for
  the transcript version it translates, which must itself be approved.
- Publishing needs an approved transcript and a consent that permits indexing.
- Any correction supersedes earlier approved content, so a published recording returns to review.
"""

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.repositories import (
    ConsentRepository,
    NewVersion,
    RecordingRepository,
    ReviewDecisionRepository,
    VersionRepository,
)
from app.index_sync import drop_index, queue_index
from app.models.records import (
    Recording,
    RecordingStatus,
    ReviewDecision,
    Right,
    Subject,
    VersionRef,
    VersionStatus,
)
from app.models.transcript import Segment
from app.security.consent import require_right

EDITABLE = (RecordingStatus.REVIEW, RecordingStatus.PUBLISHED)


class ReviewError(Exception):
    def __init__(self, code: str, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _stale() -> ReviewError:
    return ReviewError("stale_version", 409)


def _not_reviewable() -> ReviewError:
    return ReviewError("not_reviewable", 409)


def _transcript_not_approved() -> ReviewError:
    return ReviewError("transcript_not_approved", 409)


@dataclass(frozen=True)
class EditInput:
    kind: Subject
    expected_version: int
    edits: dict[str, str]
    editor: str


@dataclass(frozen=True)
class DecisionInput:
    kind: Subject
    expected_version: int
    approved: bool
    note: str | None = None


def apply_edits(base: list[Segment], edits: dict[str, str]) -> list[Segment]:
    """Replace the text of existing segments; IDs and timing never change."""
    known = {s.segment_id for s in base}
    if not edits or not set(edits) <= known:
        raise ReviewError("unknown_segment", 422)
    return [s.model_copy(update={"text": edits.get(s.segment_id, s.text)}) for s in base]


def _latest_draftable(
    versions: VersionRepository, recording: Recording, kind: Subject
) -> VersionRef:
    if recording.status not in EDITABLE:
        raise _not_reviewable()
    latest = versions.latest(recording.id, kind)
    if latest is None:
        raise _not_reviewable()
    return latest


def edit_draft(session: Session, recording: Recording, request: EditInput) -> VersionRef:
    """Save the edits as the next draft of the transcript or translation."""
    versions = VersionRepository(session)
    latest = _latest_draftable(versions, recording, request.kind)
    if latest.version != request.expected_version:
        raise _stale()
    draft = NewVersion(
        recording.id,
        request.kind,
        apply_edits(latest.segments, request.edits),
        request.editor,
        latest.transcript_version,
    )
    saved = versions.add_draft(draft)
    if recording.status == RecordingStatus.PUBLISHED:
        RecordingRepository(session).set_status(recording.id, RecordingStatus.REVIEW)
        drop_index(session, recording.id)
    return saved


def _check_translation_link(
    versions: VersionRepository, recording_id: str, latest: VersionRef
) -> None:
    transcript = versions.approved(recording_id, Subject.TRANSCRIPT)
    if transcript is None or transcript.version != latest.transcript_version:
        raise _transcript_not_approved()


def _draft_to_decide(
    versions: VersionRepository, recording: Recording, request: DecisionInput
) -> VersionRef:
    if recording.status != RecordingStatus.REVIEW:
        raise _not_reviewable()
    latest = versions.latest(recording.id, request.kind)
    if latest is None or latest.status != VersionStatus.DRAFT:
        raise _not_reviewable()
    if latest.version != request.expected_version:
        raise _stale()
    return latest


def decide(
    session: Session, recording: Recording, request: DecisionInput, reviewer_id: str
) -> VersionRef:
    """Record a reviewer's approval or rejection of the current draft."""
    versions = VersionRepository(session)
    latest = _draft_to_decide(versions, recording, request)
    if request.approved and request.kind is Subject.TRANSLATION:
        _check_translation_link(versions, recording.id, latest)
    status = VersionStatus.APPROVED if request.approved else VersionStatus.REJECTED
    versions.set_status(recording.id, request.kind, latest.version, status)
    decision = ReviewDecision(
        id=uuid4().hex,
        recording_id=recording.id,
        subject=request.kind,
        subject_version=latest.version,
        reviewer_id=reviewer_id,
        approved=request.approved,
        note=request.note,
    )
    ReviewDecisionRepository(session).add(decision)
    return latest.model_copy(update={"status": status})


def publish(session: Session, recording: Recording) -> RecordingStatus:
    """Make the approved transcript current. Needs indexing consent; safe to repeat."""
    if recording.status == RecordingStatus.PUBLISHED:
        return RecordingStatus.PUBLISHED
    if recording.status != RecordingStatus.REVIEW:
        raise _not_reviewable()
    require_right(ConsentRepository(session).get(recording.consent_id), Right.INDEXING)
    if VersionRepository(session).approved(recording.id, Subject.TRANSCRIPT) is None:
        raise _transcript_not_approved()
    RecordingRepository(session).set_status(recording.id, RecordingStatus.PUBLISHED)
    queue_index(session, recording.id)
    return RecordingStatus.PUBLISHED
