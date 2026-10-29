"""Data access. Callers get domain models, never SQLAlchemy rows."""

from dataclasses import asdict, dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.tables import (
    AppUserRow,
    AuditLogRow,
    CommunityMemberRow,
    ConsentRow,
    JobRow,
    RecordingRow,
    TranscriptVersionRow,
    TranslationVersionRow,
)
from app.models.job import Job, JobStatus
from app.models.records import (
    Consent,
    Recording,
    RecordingStatus,
    Right,
    TranscriptVersion,
    TranslationVersion,
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

    def fail_open_jobs(self, recording_ids: list[str], error: str) -> int:
        """Stop queued or running jobs for these recordings; returns how many were stopped."""
        if not recording_ids:
            return 0
        query = select(JobRow).where(
            JobRow.recording_id.in_(recording_ids),
            JobRow.status.in_([JobStatus.QUEUED, JobStatus.PROCESSING]),
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
