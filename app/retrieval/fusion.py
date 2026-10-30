"""Reciprocal rank fusion, and merging the results of several searches into one ranked list.

`reciprocal_rank_fusion` works on stable IDs. `fuse_branches` works on authorized evidence: it
removes duplicates (the same passage found by two searches), remembers which searches found it and
at what rank, and orders by the fused score. Callers pass only evidence that has already passed the
eligibility gate.
"""

from collections import defaultdict
from dataclasses import dataclass

from app.models.evidence import Evidence

RRF_K = 60
CANDIDATES_PER_BRANCH = 20


@dataclass(frozen=True)
class FusedHit:
    """A passage after fusion: its evidence, its score and where each search ranked it."""

    evidence: Evidence
    score: float
    ranks: tuple[tuple[str, int], ...]


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    if k < 1:
        raise ValueError("k must be positive")
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        seen: set[str] = set()
        for rank, item_id in enumerate(ranking, start=1):
            if item_id not in seen:
                scores[item_id] += 1.0 / (k + rank)
                seen.add(item_id)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def _merged(items: list[Evidence]) -> Evidence:
    """One evidence object carrying every method that found the passage."""
    methods = frozenset().union(*(item.retrieval_methods for item in items))
    return items[0].model_copy(update={"retrieval_methods": methods})


def _first_of_each(ranking: list[Evidence]) -> list[Evidence]:
    """The ranking with repeats of the same passage dropped, keeping the best position."""
    seen: set[str] = set()
    unique: list[Evidence] = []
    for item in ranking:
        if item.evidence_id not in seen:
            seen.add(item.evidence_id)
            unique.append(item)
    return unique


def _collect(
    unique: dict[str, list[Evidence]],
) -> tuple[dict[str, list[Evidence]], dict[str, list[tuple[str, int]]]]:
    """Group each passage's appearances, and its rank in every search that found it."""
    found: dict[str, list[Evidence]] = defaultdict(list)
    ranks: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for name, ranking in unique.items():
        for position, item in enumerate(ranking, start=1):
            found[item.evidence_id].append(item)
            ranks[item.evidence_id].append((name, position))
    return found, ranks


def fuse_branches(branches: dict[str, list[Evidence]], k: int = RRF_K) -> list[FusedHit]:
    """Fuse ranked lists from several searches. Ties break by evidence ID, so order is stable."""
    unique = {name: _first_of_each(ranking) for name, ranking in branches.items()}
    found, ranks = _collect(unique)
    scores = reciprocal_rank_fusion([[i.evidence_id for i in r] for r in unique.values()], k)
    return [
        FusedHit(_merged(found[evidence_id]), score, tuple(ranks[evidence_id]))
        for evidence_id, score in scores
    ]
