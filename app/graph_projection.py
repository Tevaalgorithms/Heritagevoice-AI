"""Rebuild the knowledge graph from PostgreSQL: the recovery and rollback path for derived data.

Every published recording that has approved assertions is projected again; anything in the graph
whose recording is no longer published (revoked, corrected, deleted) is removed.
"""

from dataclasses import dataclass

from app.db.repositories import GraphAssertionRepository, RecordingRepository
from app.indexing import IndexDeps, project_graph
from app.models.records import RecordingStatus
from app.ports import GraphProjection


@dataclass(frozen=True)
class GraphRebuildResult:
    """How many recordings were projected and how many were removed from the graph."""

    projected: int
    removed: int


def _wanted(deps: IndexDeps) -> list[str]:
    """Published recordings that have approved assertions."""
    with deps.sessions() as session:
        published = set(RecordingRepository(session).ids_by_status(RecordingStatus.PUBLISHED))
        approved = GraphAssertionRepository(session).recording_ids_with_approved()
    return [recording_id for recording_id in approved if recording_id in published]


def _leftovers(graph: GraphProjection, wanted: list[str]) -> list[str]:
    """Recordings in the graph that should no longer be there."""
    return [recording_id for recording_id in graph.recording_ids() if recording_id not in wanted]


def rebuild_graph(deps: IndexDeps) -> GraphRebuildResult:
    if deps.graph is None:
        return GraphRebuildResult(projected=0, removed=0)
    wanted = _wanted(deps)
    leftovers = _leftovers(deps.graph, wanted)
    for recording_id in wanted:
        project_graph(deps, recording_id)
    for recording_id in leftovers:
        deps.graph.delete_recording(recording_id)
    return GraphRebuildResult(projected=len(wanted), removed=len(leftovers))
