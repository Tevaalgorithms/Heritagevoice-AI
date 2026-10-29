"""Processing states a recording moves through; `published` only after human approval."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    REVIEW = "review"
    PUBLISHED = "published"
    FAILED = "failed"


class Job(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    kind: str
    status: JobStatus
    error: str | None = None
