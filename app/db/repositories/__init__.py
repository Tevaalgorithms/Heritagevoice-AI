"""Data access. Callers get domain models, never SQLAlchemy rows. One module per topic.

Import repositories from here (`from app.db.repositories import JobRepository`); the module they
live in is an implementation detail.
"""

from app.db.repositories.audit import AuditEntry, AuditRepository
from app.db.repositories.chunks import ChunkRepository
from app.db.repositories.consents import ConsentRepository
from app.db.repositories.jobs import JobRepository
from app.db.repositories.model_settings import ModelCatalogRepository, ModelSettingRepository
from app.db.repositories.recordings import RecordingRepository
from app.db.repositories.transcripts import (
    NewVersion,
    ReviewDecisionRepository,
    TranscriptRepository,
    VersionRepository,
)
from app.db.repositories.users import UserRepository

__all__ = [
    "AuditEntry",
    "AuditRepository",
    "ChunkRepository",
    "ConsentRepository",
    "JobRepository",
    "ModelCatalogRepository",
    "ModelSettingRepository",
    "NewVersion",
    "RecordingRepository",
    "ReviewDecisionRepository",
    "TranscriptRepository",
    "UserRepository",
    "VersionRepository",
]
