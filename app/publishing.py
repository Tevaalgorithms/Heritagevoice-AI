"""Turn an approved, reviewed recording into searchable evidence. Drafts never get here."""

import hashlib

from app.graph.state import PreservationState
from app.models.evidence import Evidence
from app.models.job import JobStatus
from app.models.transcript import Segment
from app.ports import VectorStore


def to_evidence(
    recording_id: str, segment: Segment, translation: Segment, access_groups: frozenset[str]
) -> Evidence:
    return Evidence(
        evidence_id=f"{recording_id}:{segment.segment_id}:v1",
        document_id=recording_id,
        document_version="v1",
        chunk_id=segment.segment_id,
        title=f"Recording {recording_id}",
        locator=f"audio:{recording_id}?t={segment.start_s}-{segment.end_s}",
        passage=translation.text,
        passage_hash=hashlib.sha256(translation.text.encode()).hexdigest(),
        access_groups=access_groups,
        retrieval_methods=frozenset({"vector"}),
    )


def publish_recording(
    state: PreservationState, approved: bool, store: VectorStore, access_groups: frozenset[str]
) -> list[Evidence]:
    if not approved or state.get("status") != JobStatus.REVIEW:
        raise PermissionError("Only an approved recording in review can be published")
    items = [
        to_evidence(state["recording_id"], seg, tr, access_groups)
        for seg, tr in zip(state["segments"], state["translations"], strict=True)
    ]
    store.upsert(items)
    return items
