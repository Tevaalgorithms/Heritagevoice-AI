"""Keep the indexes in step with the review workflow. Called inside the caller's transaction."""

from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.repositories import ChunkRepository, JobRepository
from app.graph_extraction import EXTRACT_KIND
from app.indexing import INDEX_KIND, UNINDEX_KIND


def queue_index(session: Session, recording_id: str) -> None:
    """Content was published: ask the worker to index it."""
    JobRepository(session).create(uuid4().hex, INDEX_KIND, recording_id)


def queue_graph_extraction(session: Session, recording_id: str) -> None:
    """Content was published: ask the worker to propose graph relationships for review."""
    JobRepository(session).create(uuid4().hex, EXTRACT_KIND, recording_id)


def drop_index(session: Session, recording_id: str) -> None:
    """Content was corrected or revoked: keyword results vanish now; a job removes the vectors."""
    ChunkRepository(session).delete_for_recording(recording_id)
    JobRepository(session).create(uuid4().hex, UNINDEX_KIND, recording_id)
