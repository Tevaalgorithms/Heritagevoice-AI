"""Data access. Callers get domain models, never SQLAlchemy rows."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.tables import JobRow
from app.models.job import Job, JobStatus


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
