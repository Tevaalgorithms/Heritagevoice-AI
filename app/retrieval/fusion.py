"""Pure reciprocal rank fusion; caller supplies already-authorized stable IDs."""

from collections import defaultdict


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
