"""Processing states a recording moves through; `published` only after human approval."""

from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    REVIEW = "review"
    PUBLISHED = "published"
    FAILED = "failed"
