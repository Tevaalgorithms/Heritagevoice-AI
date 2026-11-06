"""Background jobs: queueing, claiming, progress and outcomes."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.tables import (
    JobRow,
)
from app.models.job import Job, JobStatus


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
    """Creates, claims and updates background jobs."""

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

    def is_open(self, kind: str, recording_id: str) -> bool:
        """Whether a job of this kind for this recording is waiting or running."""
        query = select(JobRow.id).where(
            JobRow.kind == kind,
            JobRow.recording_id == recording_id,
            JobRow.status.in_([JobStatus.QUEUED, JobStatus.PROCESSING]),
        )
        return self._session.scalars(query.limit(1)).first() is not None

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
