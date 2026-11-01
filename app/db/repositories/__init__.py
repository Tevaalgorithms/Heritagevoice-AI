"""Data access. Callers get domain models, never SQLAlchemy rows. One module per topic.

Import repositories from here (`from app.db.repositories import JobRepository`); the module they
live in is an implementation detail.
"""

from app.db.repositories.audit import AuditEntry, AuditRepository
from app.db.repositories.chunks import ChunkRepository
from app.db.repositories.communities import CommunityRepository
from app.db.repositories.consents import ConsentRepository
from app.db.repositories.graph import GraphAssertionRepository
from app.db.repositories.jobs import JobRepository
from app.db.repositories.model_settings import ModelCatalogRepository, ModelSettingRepository
from app.db.repositories.recordings import RecordingRepository
from app.db.repositories.reports import ReportRepository
from app.db.repositories.transcripts import (
    NewVersion,
    ReviewDecisionRepository,
    TranscriptRepository,
    VersionRepository,
)
from app.db.repositories.usage import UsageRepository
from app.db.repositories.users import UserRepository

__all__ = [
    "AuditEntry",
    "AuditRepository",
    "ChunkRepository",
    "CommunityRepository",
    "ConsentRepository",
    "GraphAssertionRepository",
    "JobRepository",
    "ModelCatalogRepository",
    "ModelSettingRepository",
    "UsageRepository",
    "NewVersion",
    "RecordingRepository",
    "ReportRepository",
    "ReviewDecisionRepository",
    "TranscriptRepository",
    "UserRepository",
    "VersionRepository",
]
