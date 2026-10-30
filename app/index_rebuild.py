"""Rebuild both indexes from PostgreSQL: the recovery and rollback path for derived data.

Every published recording is re-chunked and re-embedded from its approved versions; anything
indexed that is no longer published (revoked, corrected, deleted) is removed.
"""

from dataclasses import dataclass

from app.db.repositories import ChunkRepository, RecordingRepository
from app.indexing import IndexDeps, IndexRefusedError, index_one, remove_recording
from app.models.records import RecordingStatus


@dataclass(frozen=True)
class RebuildResult:
    """How many chunks a rebuild indexed and how many it removed."""

    indexed: int
    removed: int


def _index_or_remove(deps: IndexDeps, recording_id: str) -> bool:
    """True if the recording was indexed, False if it had to be removed instead."""
    try:
        index_one(deps, recording_id)
    except IndexRefusedError:
        remove_recording(deps, recording_id)
        return False
    return True


def rebuild_all(deps: IndexDeps) -> RebuildResult:
    with deps.sessions() as session:
        published = RecordingRepository(session).ids_by_status(RecordingStatus.PUBLISHED)
        leftovers = [i for i in ChunkRepository(session).recording_ids() if i not in published]
    outcomes = [_index_or_remove(deps, recording_id) for recording_id in published]
    for recording_id in leftovers:
        remove_recording(deps, recording_id)
    return RebuildResult(indexed=sum(outcomes), removed=outcomes.count(False) + len(leftovers))
