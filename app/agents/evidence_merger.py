"""Merge identical chunks without erasing retrieval or relationship provenance."""

from app.graph.state import StateUpdate, WorkflowState
from app.models.evidence import Evidence


def _identity(item: Evidence) -> tuple[str, str, frozenset[str], str]:
    return (item.passage, item.passage_hash, item.access_groups, item.evidence_id)


def _combine(previous: Evidence, item: Evidence) -> Evidence:
    if _identity(previous) != _identity(item):
        raise ValueError("Inconsistent source identity or access labels")
    return previous.model_copy(
        update={
            "retrieval_methods": previous.retrieval_methods | item.retrieval_methods,
            "graph_paths": tuple(sorted(set(previous.graph_paths + item.graph_paths))),
        }
    )


def merge_evidence(items: list[Evidence]) -> list[Evidence]:
    merged: dict[tuple[str, str, str], Evidence] = {}
    for item in items:
        key = (item.document_id, item.document_version, item.chunk_id)
        merged[key] = _combine(merged[key], item) if key in merged else item
    return list(merged.values())


def merge(state: WorkflowState) -> StateUpdate:
    return {
        "evidence": merge_evidence(
            state.get("hybrid_evidence", []) + state.get("graph_evidence", [])
        )
    }
