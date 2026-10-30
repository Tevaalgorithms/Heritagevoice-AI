"""Transcript and translation drafts, their versions, and review decisions."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.tables import (
    RecordingRow,
    ReviewDecisionRow,
    TranscriptVersionRow,
    TranslationVersionRow,
)
from app.models.records import (
    RecordingStatus,
    ReviewDecision,
    Subject,
    TranscriptVersion,
    TranslationVersion,
    VersionRef,
    VersionStatus,
)
from app.models.transcript import Segment


def _segments(raw: list[dict[str, object]]) -> list[Segment]:
    return [Segment.model_validate(item) for item in raw]


class TranscriptRepository:
    """Drafts are stored with status `draft`; only `approved` versions are ever searchable."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save_draft(
        self, recording_id: str, segments: list[Segment], created_by: str
    ) -> TranscriptVersion:
        latest = self._latest_row(recording_id)
        version = 1 if latest is None else latest.version + 1
        row = TranscriptVersionRow(
            id=f"{recording_id}:t{version}",
            recording_id=recording_id,
            version=version,
            status=VersionStatus.DRAFT,
            segments=[s.model_dump(mode="json") for s in segments],
            created_by=created_by,
        )
        self._session.add(row)
        self._session.flush()
        return self._to_version(row)

    def latest(self, recording_id: str) -> TranscriptVersion | None:
        row = self._latest_row(recording_id)
        return None if row is None else self._to_version(row)

    def approved_segments(self, recording_id: str) -> list[Segment]:
        query = (
            select(TranscriptVersionRow)
            .join(RecordingRow, RecordingRow.id == TranscriptVersionRow.recording_id)
            .where(
                TranscriptVersionRow.recording_id == recording_id,
                TranscriptVersionRow.status == VersionStatus.APPROVED,
                RecordingRow.status != RecordingStatus.REVOKED,
            )
            .order_by(TranscriptVersionRow.version.desc())
            .limit(1)
        )
        row = self._session.scalars(query).first()
        return [] if row is None else _segments(row.segments)

    def save_translation_draft(self, draft: TranslationVersion) -> TranslationVersion:
        self._session.add(
            TranslationVersionRow(
                id=draft.id,
                recording_id=draft.recording_id,
                transcript_version=draft.transcript_version,
                version=draft.version,
                target_language=draft.target_language,
                status=draft.status,
                segments=[seg.model_dump(mode="json") for seg in draft.segments],
                created_by=draft.created_by,
            )
        )
        self._session.flush()
        return draft

    def latest_translation(self, recording_id: str) -> TranslationVersion | None:
        query = (
            select(TranslationVersionRow)
            .where(TranslationVersionRow.recording_id == recording_id)
            .order_by(TranslationVersionRow.version.desc())
            .limit(1)
        )
        row = self._session.scalars(query).first()
        if row is None:
            return None
        return TranslationVersion(
            id=row.id,
            recording_id=row.recording_id,
            transcript_version=row.transcript_version,
            version=row.version,
            target_language=row.target_language,
            status=VersionStatus(row.status),
            segments=_segments(row.segments),
            created_by=row.created_by,
        )

    def _latest_row(self, recording_id: str) -> TranscriptVersionRow | None:
        query = (
            select(TranscriptVersionRow)
            .where(TranscriptVersionRow.recording_id == recording_id)
            .order_by(TranscriptVersionRow.version.desc())
            .limit(1)
        )
        return self._session.scalars(query).first()

    @staticmethod
    def _to_version(row: TranscriptVersionRow) -> TranscriptVersion:
        return TranscriptVersion(
            id=row.id,
            recording_id=row.recording_id,
            version=row.version,
            status=VersionStatus(row.status),
            segments=_segments(row.segments),
            created_by=row.created_by,
        )


VersionRow = TranscriptVersionRow | TranslationVersionRow


LIVE = (VersionStatus.DRAFT, VersionStatus.APPROVED)


@dataclass(frozen=True)
class NewVersion:
    """The inputs needed to save a new draft version."""

    recording_id: str
    kind: Subject
    segments: list[Segment]
    editor: str
    transcript_version: int | None = None


class VersionRepository:
    """Transcript and translation versions share one workflow: draft, approved or superseded."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _model(kind: Subject) -> type[VersionRow]:
        return TranscriptVersionRow if kind is Subject.TRANSCRIPT else TranslationVersionRow

    def _rows(self, recording_id: str, kind: Subject) -> list[VersionRow]:
        model = self._model(kind)
        query = (
            select(model).where(model.recording_id == recording_id).order_by(model.version.desc())
        )
        return list(self._session.scalars(query))

    def latest(self, recording_id: str, kind: Subject) -> VersionRef | None:
        rows = self._rows(recording_id, kind)
        return self._ref(kind, rows[0]) if rows else None

    def approved(self, recording_id: str, kind: Subject) -> VersionRef | None:
        approved = [r for r in self._rows(recording_id, kind) if r.status == VersionStatus.APPROVED]
        return self._ref(kind, approved[0]) if approved else None

    def add_draft(self, draft: NewVersion) -> VersionRef:
        """Supersede any live version, then store the new draft with the next version number."""
        rows = self._rows(draft.recording_id, draft.kind)
        for row in rows:
            if row.status in LIVE:
                row.status = VersionStatus.SUPERSEDED
        version = 1 + max((r.version for r in rows), default=0)
        self._session.add(self._new_row(draft, version))
        self._session.flush()
        return VersionRef(
            kind=draft.kind,
            version=version,
            status=VersionStatus.DRAFT,
            segments=draft.segments,
            transcript_version=draft.transcript_version,
        )

    def set_status(
        self, recording_id: str, kind: Subject, version: int, status: VersionStatus
    ) -> None:
        for row in self._rows(recording_id, kind):
            if row.version == version:
                row.status = status
            elif status == VersionStatus.APPROVED and row.status == VersionStatus.APPROVED:
                row.status = VersionStatus.SUPERSEDED
        self._session.flush()

    @staticmethod
    def _new_row(draft: NewVersion, version: int) -> VersionRow:
        data = [seg.model_dump(mode="json") for seg in draft.segments]
        if draft.kind is Subject.TRANSCRIPT:
            return TranscriptVersionRow(
                id=f"{draft.recording_id}:t{version}",
                recording_id=draft.recording_id,
                version=version,
                status=VersionStatus.DRAFT,
                segments=data,
                created_by=draft.editor,
            )
        return TranslationVersionRow(
            id=f"{draft.recording_id}:en:v{version}",
            recording_id=draft.recording_id,
            transcript_version=draft.transcript_version or version,
            version=version,
            target_language="en",
            status=VersionStatus.DRAFT,
            segments=data,
            created_by=draft.editor,
        )

    @staticmethod
    def _ref(kind: Subject, row: VersionRow) -> VersionRef:
        return VersionRef(
            kind=kind,
            version=row.version,
            status=VersionStatus(row.status),
            segments=_segments(row.segments),
            transcript_version=getattr(row, "transcript_version", None),
        )


class ReviewDecisionRepository:
    """Stores each reviewer's approval or rejection."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, decision: ReviewDecision) -> None:
        self._session.add(ReviewDecisionRow(**decision.model_dump(mode="json")))
        self._session.flush()

    def for_recording(self, recording_id: str) -> list[ReviewDecision]:
        query = select(ReviewDecisionRow).where(ReviewDecisionRow.recording_id == recording_id)
        return [
            ReviewDecision(
                id=r.id,
                recording_id=r.recording_id,
                subject=Subject(r.subject),
                subject_version=r.subject_version,
                reviewer_id=r.reviewer_id,
                approved=r.approved,
                note=r.note,
            )
            for r in self._session.scalars(query)
        ]
