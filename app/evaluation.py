"""Measure how well an embedding model retrieves the expected sources (the embedding bake-off).

Each segment is indexed in its own language and, when present, its English translation, so a
question in either language can find it. A question is a hit when any expected `recording:segment`
appears in the top k results. Run it for each candidate model and keep the JSON reports.
"""

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.ports import Embedder

TOP_K = 5


def load_fixtures(directory: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    recordings = json.loads((directory / "recordings.json").read_text())["recordings"]
    questions = json.loads((directory / "questions.json").read_text())["questions"]
    return recordings, questions


def passages(recordings: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """(source, text) pairs, where source is `recording:segment`."""
    found: list[tuple[str, str]] = []
    for recording in recordings:
        for segment in recording["segments"]:
            source = f"{recording['id']}:{segment['segment_id']}"
            found.append((source, segment["text"]))
            if segment.get("translation") not in (None, segment["text"]):
                found.append((source, segment["translation"]))
    return found


def _cosine(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm if norm else 0.0


def _ranked_sources(
    query: list[float], vectors: list[list[float]], sources: list[str]
) -> list[str]:
    order = sorted(range(len(sources)), key=lambda i: -_cosine(query, vectors[i]))
    ranked: list[str] = []
    for i in order:
        if sources[i] not in ranked:
            ranked.append(sources[i])
    return ranked


def _reciprocal_rank(ranked: list[str], expected: set[str]) -> float:
    for position, source in enumerate(ranked, start=1):
        if source in expected:
            return 1.0 / position
    return 0.0


def _bucket(question: dict[str, Any]) -> str:
    return f"{question['category']}/{question['language']}"


def _score_question(
    question: dict[str, Any], embedder: Embedder, vectors: list[list[float]], sources: list[str]
) -> tuple[str, bool, float]:
    expected = set(question["expected_sources"])
    ranked = _ranked_sources(embedder.embed_query(question["question"]), vectors, sources)
    return (
        _bucket(question),
        bool(expected & set(ranked[:TOP_K])),
        _reciprocal_rank(ranked, expected),
    )


def _recall(results: list[tuple[str, bool, float]]) -> dict[str, list[bool]]:
    hits: dict[str, list[bool]] = defaultdict(list)
    for bucket, hit, _ in results:
        hits[bucket].append(hit)
        hits["all"].append(hit)
    return hits


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _report(results: list[tuple[str, bool, float]]) -> dict[str, Any]:
    hits = _recall(results)
    return {
        "k": TOP_K,
        "recall_at_k": {
            name: _mean([float(h) for h in found]) for name, found in sorted(hits.items())
        },
        "cases": {name: len(found) for name, found in sorted(hits.items())},
        "mrr": _mean([rr for _, _, rr in results]),
    }


def _embed_passages(
    embedder: Embedder, recordings: list[dict[str, Any]]
) -> tuple[list[list[float]], list[str]]:
    pairs = passages(recordings)
    return embedder.embed_passages([text for _, text in pairs]), [source for source, _ in pairs]


def _answerable(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [q for q in questions if q["answerable"]]


def evaluate(
    embedder: Embedder, recordings: list[dict[str, Any]], questions: list[dict[str, Any]]
) -> dict[str, Any]:
    vectors, sources = _embed_passages(embedder, recordings)
    scored = [_score_question(q, embedder, vectors, sources) for q in _answerable(questions)]
    return _report(scored)
