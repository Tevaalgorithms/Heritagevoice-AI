"""Data access. Callers get domain models, never SQLAlchemy rows."""

from dataclasses import asdict, dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.tables import (
    AppUserRow,
    AuditLogRow,
    CommunityMemberRow,
    ConsentRow,
    EvidenceChunkRow,
    JobRow,
    ModelSettingRow,
    RecordingRow,
    ReviewDecisionRow,
    TranscriptVersionRow,
    TranslationVersionRow,
)
from app.models.index import ChunkKind, ChunkRecord
from app.models.job import Job, JobStatus
from app.models.llm import ModelParams, ModelRole, ModelSetting, Provider
from app.models.records import (
    Consent,
    Recording,
    RecordingStatus,
    ReviewDecision,
    Right,
    Subject,
    TranscriptVersion,
    TranslationVersion,
    VersionRef,
    VersionStatus,
)
from app.models.transcript import Segment
from app.models.users import StoredUser, UserStatus
from app.security.roles import Role


def _to_job(row: JobRow) -> Job:
    return Job(
        id=row.id,
        kind=row.kind,
        status=JobStatus(row.status),
        error=row.error,
        stage=row.stage,
        attempts=row.attempts,
        recording_id=row.recording_id,
    )


class JobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, job_id: str, kind: str, recording_id: str | None = None) -> Job:
        row = JobRow(
            id=job_id, kind=kind, status=JobStatus.QUEUED, attempts=0, recording_id=recording_id
        )
        self._session.add(row)
        self._session.flush()
        return _to_job(row)

    def get(self, job_id: str) -> Job | None:
        row = self._session.get(JobRow, job_id)
        return None if row is None else _to_job(row)

    def set_status(self, job_id: str, status: JobStatus, error: str | None = None) -> None:
        row = self._session.get(JobRow, job_id)
        if row is None:
            raise KeyError(job_id)
        row.status, row.error = status, error

    def fail_open_jobs(
        self, recording_ids: list[str], error: str, keep_kinds: tuple[str, ...] = ()
    ) -> int:
        """Stop queued or running jobs for these recordings, except `keep_kinds` (clean-up jobs)."""
        if not recording_ids:
            return 0
        query = select(JobRow).where(
            JobRow.recording_id.in_(recording_ids),
            JobRow.status.in_([JobStatus.QUEUED, JobStatus.PROCESSING]),
            JobRow.kind.not_in(keep_kinds),
        )
        rows = list(self._session.scalars(query))
        for row in rows:
            row.status, row.error = JobStatus.FAILED, error
        self._session.flush()
        return len(rows)

    def by_recording(self, recording_id: str) -> Job | None:
        query = select(JobRow).where(JobRow.recording_id == recording_id).limit(1)
        row = self._session.scalars(query).first()
        return None if row is None else _to_job(row)

    def set_stage(self, job_id: str, stage: str) -> None:
        self._row(job_id).stage = stage

    def requeue(self, job_id: str) -> None:
        row = self._row(job_id)
        row.status, row.error = JobStatus.QUEUED, None

    def _row(self, job_id: str) -> JobRow:
        row = self._session.get(JobRow, job_id)
        if row is None:
            raise KeyError(job_id)
        return row

    def claim_next_queued(self) -> Job | None:
        query = (
            select(JobRow)
            .where(JobRow.status == JobStatus.QUEUED)
            .order_by(JobRow.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        row = self._session.scalars(query).first()
        if row is None:
            return None
        row.status, row.attempts = JobStatus.PROCESSING, row.attempts + 1
        self._session.flush()
        return _to_job(row)


class UserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, sub: str, role: Role, communities: frozenset[str]) -> StoredUser:
        self._session.add(AppUserRow(sub=sub, role=role, status=UserStatus.ACTIVE))
        self._session.flush()
        self.set_communities(sub, communities)
        return self._require(sub)

    def get(self, sub: str) -> StoredUser | None:
        row = self._session.get(AppUserRow, sub)
        return None if row is None else self._to_user(row)

    def set_role(self, sub: str, role: Role) -> None:
        self._row(sub).role = role

    def set_status(self, sub: str, status: UserStatus) -> None:
        self._row(sub).status = status

    def set_communities(self, sub: str, communities: frozenset[str]) -> None:
        self._row(sub)
        self._session.execute(delete(CommunityMemberRow).where(CommunityMemberRow.user_sub == sub))
        self._session.add_all(CommunityMemberRow(user_sub=sub, community_id=c) for c in communities)
        self._session.flush()

    def _row(self, sub: str) -> AppUserRow:
        row = self._session.get(AppUserRow, sub)
        if row is None:
            raise KeyError(sub)
        return row

    def _require(self, sub: str) -> StoredUser:
        return self._to_user(self._row(sub))

    def _to_user(self, row: AppUserRow) -> StoredUser:
        query = select(CommunityMemberRow.community_id).where(
            CommunityMemberRow.user_sub == row.sub
        )
        communities = frozenset(self._session.scalars(query))
        return StoredUser(
            sub=row.sub,
            role=Role(row.role),
            status=UserStatus(row.status),
            communities=communities,
        )


@dataclass(frozen=True)
class AuditEntry:
    """Who did what to whom. `detail` is a short admin-written note, never recording content."""

    actor_sub: str
    action: str
    target: str
    trace_id: str
    detail: str | None = None


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, entry: AuditEntry) -> None:
        self._session.add(AuditLogRow(**asdict(entry)))
        self._session.flush()


def _to_consent(row: ConsentRow) -> Consent:
    return Consent(
        id=row.id,
        community_id=row.community_id,
        rights=frozenset(Right(r) for r in row.rights),
        policy_version=row.policy_version,
        revoked=row.revoked,
    )


class ConsentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, consent: Consent) -> None:
        self._session.add(
            ConsentRow(
                id=consent.id,
                community_id=consent.community_id,
                rights=sorted(r.value for r in consent.rights),
                policy_version=consent.policy_version,
                revoked=consent.revoked,
            )
        )
        self._session.flush()

    def get(self, consent_id: str) -> Consent | None:
        row = self._session.get(ConsentRow, consent_id)
        return None if row is None else _to_consent(row)

    def revoke(self, consent_id: str) -> bool:
        """Mark the consent revoked; False if it does not exist. Idempotent."""
        row = self._session.get(ConsentRow, consent_id)
        if row is None:
            return False
        row.revoked = True
        self._session.flush()
        return True


def _to_recording(row: RecordingRow) -> Recording:
    return Recording(
        id=row.id,
        community_id=row.community_id,
        uploader_id=row.uploader_id,
        language=row.language,
        consent_id=row.consent_id,
        status=RecordingStatus(row.status),
        audio_key=row.audio_key,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        duration_s=row.duration_s,
    )


class RecordingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, recording: Recording, idempotency_key: str | None = None) -> Recording:
        self._session.add(
            RecordingRow(**recording.model_dump(mode="json"), idempotency_key=idempotency_key)
        )
        self._session.flush()
        return recording

    def get(self, recording_id: str) -> Recording | None:
        row = self._session.get(RecordingRow, recording_id)
        return None if row is None else _to_recording(row)

    def find_by_idempotency(self, uploader_id: str, key: str) -> Recording | None:
        query = select(RecordingRow).where(
            RecordingRow.uploader_id == uploader_id, RecordingRow.idempotency_key == key
        )
        row = self._session.scalars(query).first()
        return None if row is None else _to_recording(row)

    def list_for(self, communities: frozenset[str], owner_id: str | None) -> list[Recording]:
        """Recordings in these communities; only the owner's own when `owner_id` is given."""
        query = select(RecordingRow).where(RecordingRow.community_id.in_(communities))
        if owner_id is not None:
            query = query.where(RecordingRow.uploader_id == owner_id)
        query = query.order_by(RecordingRow.created_at.desc()).limit(200)
        return [_to_recording(r) for r in self._session.scalars(query)]

    def ids_by_status(self, status: RecordingStatus) -> list[str]:
        query = select(RecordingRow.id).where(RecordingRow.status == status)
        return sorted(self._session.scalars(query))

    def ids_by_consent(self, consent_id: str) -> list[str]:
        query = select(RecordingRow.id).where(RecordingRow.consent_id == consent_id)
        return list(self._session.scalars(query))

    def set_status(self, recording_id: str, status: RecordingStatus) -> None:
        row = self._session.get(RecordingRow, recording_id)
        if row is None:
            raise KeyError(recording_id)
        row.status = status


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


def _to_setting(row: ModelSettingRow) -> ModelSetting:
    return ModelSetting(
        role=ModelRole(row.role),
        provider=Provider(row.provider),
        model=row.model,
        temperature=row.temperature,
        timeout_s=row.timeout_s,
        max_retries=row.max_retries,
    )


class ModelSettingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, role: ModelRole) -> ModelSetting | None:
        row = self._session.get(ModelSettingRow, role.value)
        return None if row is None else _to_setting(row)

    def list_all(self) -> list[ModelSetting]:
        return [_to_setting(r) for r in self._session.scalars(select(ModelSettingRow))]

    def upsert(self, role: ModelRole, params: ModelParams, updated_by: str) -> ModelSetting:
        values = {**params.model_dump(mode="json"), "updated_by": updated_by}
        row = self._session.get(ModelSettingRow, role.value)
        if row is None:
            row = ModelSettingRow(role=role.value, **values)
            self._session.add(row)
        else:
            for name, value in values.items():
                setattr(row, name, value)
        self._session.flush()
        return _to_setting(row)

    def delete(self, role: ModelRole) -> bool:
        row = self._session.get(ModelSettingRow, role.value)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True


def _to_chunk(row: EvidenceChunkRow) -> ChunkRecord:
    return ChunkRecord(
        evidence_id=row.evidence_id,
        recording_id=row.recording_id,
        community_id=row.community_id,
        kind=ChunkKind(row.kind),
        version=row.version,
        chunk_index=row.chunk_index,
        language=row.language,
        text=row.text,
        passage_hash=row.passage_hash,
        start_s=row.start_s,
        end_s=row.end_s,
        segment_ids=tuple(row.segment_ids),
        speaker=row.speaker,
    )


class ChunkRepository:
    """The searchable copy of approved content. Rows are replaced or deleted as content changes."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def replace_for_recording(self, recording_id: str, chunks: list[ChunkRecord]) -> None:
        self.delete_for_recording(recording_id)
        for chunk in chunks:
            self._session.add(EvidenceChunkRow(**chunk.model_dump(mode="json")))
        self._session.flush()

    def delete_for_recording(self, recording_id: str) -> int:
        result = self._session.execute(
            delete(EvidenceChunkRow).where(EvidenceChunkRow.recording_id == recording_id)
        )
        self._session.flush()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    def get_many(self, evidence_ids: list[str]) -> list[ChunkRecord]:
        """Chunks for these IDs, in the order given; unknown IDs are skipped."""
        if not evidence_ids:
            return []
        query = select(EvidenceChunkRow).where(EvidenceChunkRow.evidence_id.in_(evidence_ids))
        found = {r.evidence_id: _to_chunk(r) for r in self._session.scalars(query)}
        return [found[i] for i in evidence_ids if i in found]

    def for_communities(self, communities: frozenset[str], limit: int = 5000) -> list[ChunkRecord]:
        query = (
            select(EvidenceChunkRow)
            .where(EvidenceChunkRow.community_id.in_(communities))
            .order_by(EvidenceChunkRow.evidence_id)
            .limit(limit)
        )
        return [_to_chunk(r) for r in self._session.scalars(query)]

    def recording_ids(self) -> list[str]:
        """Recordings that currently have indexed chunks."""
        return sorted(set(self._session.scalars(select(EvidenceChunkRow.recording_id))))

    def ids_for_recording(self, recording_id: str) -> list[str]:
        query = select(EvidenceChunkRow.evidence_id).where(
            EvidenceChunkRow.recording_id == recording_id
        )
        return sorted(self._session.scalars(query))
