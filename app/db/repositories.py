"""Data access. Callers get domain models, never SQLAlchemy rows."""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.tables import AppUserRow, AuditLogRow, CommunityMemberRow, JobRow
from app.models.job import Job, JobStatus
from app.models.users import StoredUser, UserStatus
from app.security.roles import Role


def _to_job(row: JobRow) -> Job:
    return Job(id=row.id, kind=row.kind, status=JobStatus(row.status), error=row.error)


class JobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, job_id: str, kind: str) -> Job:
        row = JobRow(id=job_id, kind=kind, status=JobStatus.QUEUED)
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
        row.status = JobStatus.PROCESSING
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


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, actor_sub: str, action: str, target: str, trace_id: str) -> None:
        row = AuditLogRow(actor_sub=actor_sub, action=action, target=target, trace_id=trace_id)
        self._session.add(row)
        self._session.flush()
