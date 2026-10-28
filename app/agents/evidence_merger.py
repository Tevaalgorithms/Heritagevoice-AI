"""Merge identical chunks without erasing retrieval or relationship provenance."""

from app.graph.state import WorkflowState
from app.models.evidence import Evidence


def merge_evidence(items: list[Evidence]) -> list[Evidence]:
    merged: dict[tuple[str, str, str], Evidence] = {}
    for item in items:
        key = (item.document_id, item.document_version, item.chunk_id)
        previous = merged.get(key)
        if previous is None:
            merged[key] = item
            continue
        if (
            previous.passage != item.passage
            or previous.passage_hash != item.passage_hash
            or previous.access_groups != item.access_groups
            or previous.evidence_id != item.evidence_id
        ):
            raise ValueError("Inconsistent source identity or access labels")
        merged[key] = previous.model_copy(
            update={
                "retrieval_methods": previous.retrieval_methods | item.retrieval_methods,
                "graph_paths": tuple(sorted(set(previous.graph_paths + item.graph_paths))),
            }
        )
    return list(merged.values())


def merge(state: WorkflowState) -> dict:
    return {
        "evidence": merge_evidence(
            state.get("hybrid_evidence", []) + state.get("graph_evidence", [])
        )
    }
