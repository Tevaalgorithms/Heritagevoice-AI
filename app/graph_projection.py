"""Rebuild the knowledge graph from PostgreSQL: the recovery and rollback path for derived data.

Every published recording that has approved assertions is projected again; anything in the graph
whose recording is no longer published (revoked, corrected, deleted) is removed.
"""

from dataclasses import dataclass

from app.db.repositories import GraphAssertionRepository, RecordingRepository
from app.indexing import IndexDeps, project_graph
from app.models.job import Job, JobStatus, Outcome
from app.models.records import RecordingStatus

PROJECT_KIND = "project_graph"


@dataclass(frozen=True)
class GraphRebuildResult:
    """How many recordings were projected and how many were removed from the graph."""

    projected: int
    removed: int


def _wanted(deps: IndexDeps) -> set[str]:
    """Published recordings that have approved assertions."""
    with deps.sessions() as session:
        published = set(RecordingRepository(session).ids_by_status(RecordingStatus.PUBLISHED))
        approved = GraphAssertionRepository(session).recording_ids_with_approved()
    return published.intersection(approved)


def rebuild_graph(deps: IndexDeps) -> GraphRebuildResult:
    """Project every wanted recording again and remove whatever else is in the graph."""
    if deps.graph is None:
        return GraphRebuildResult(projected=0, removed=0)
    wanted = _wanted(deps)
    leftovers = set(deps.graph.recording_ids()) - wanted
    for recording_id in sorted(wanted):
        project_graph(deps, recording_id)
    for recording_id in sorted(leftovers):
        deps.graph.delete_recording(recording_id)
    return GraphRebuildResult(projected=len(wanted), removed=len(leftovers))


def project_recording(job: Job, deps: IndexDeps) -> Outcome:
    """The job queued after a review decision: bring the graph in line with the database."""
    project_graph(deps, job.recording_id or "")
    return Outcome(status=JobStatus.PUBLISHED)
