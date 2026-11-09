"""Run the retrieval evaluation and write a dated, versioned report that can be published.

    uv run python -m evals.report              # fake word-based vector index plus keyword search
    uv run python -m evals.report --keyword    # keyword search only

Writes `evals/results/published/<date>-retrieval-<index>-<commit>.json`: the commit, the corpus
(synthetic, with its size), the kind of vector index, every case's outcome, the totals with their
denominators, and how long each question took. Only SYNTHETIC fixtures are ever used here, which is
why these reports, unlike the rest of `evals/results/`, are committed. A run on real material must
never write to this folder.
"""

import argparse
import json
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.retrieval_evaluation import TOP, distinct_recordings, first_rank, recording_of
from evals.langsmith_eval import _fixtures
from evals.retrieval_check import retriever_for

PUBLISHED = Path(__file__).parent / "results" / "published"
SCHEMA = 1


def _git(*args: str) -> str:
    done = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    return done.stdout.strip()


def _ask(retrieve: Any, question: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    returned = distinct_recordings(retrieve(question["question"]))
    millis = (time.perf_counter() - started) * 1000
    expected = sorted({recording_of(s) for s in question["expected_sources"]})
    rank = first_rank(returned, set(expected)) if expected else None
    return {
        "id": question["id"],
        "corpus": question["corpus"],
        "category": question["category"],
        "language": question["language"],
        "question": question["question"],
        "expected": expected,
        "returned": returned[:TOP],
        "rank": rank,
        "hit_at_5": None if not expected else int(rank is not None and rank <= TOP),
        "latency_ms": round(millis, 1),
    }


def _share(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Of these cases, how many were found in the top results (the denominator is shown)."""
    scored = [c for c in cases if c["hit_at_5"] is not None]
    hits = sum(c["hit_at_5"] for c in scored)
    ranks = [1 / c["rank"] if c["rank"] else 0.0 for c in scored]
    return {
        "answerable_questions": len(scored),
        "found_in_top_5": hits,
        "recall_at_5": round(hits / len(scored), 3) if scored else None,
        "mean_reciprocal_rank": round(sum(ranks) / len(ranks), 3) if ranks else None,
    }


def _grouped(cases: list[dict[str, Any]], field: str) -> dict[str, Any]:
    names = sorted({c[field] for c in cases})
    return {name: _share([c for c in cases if c[field] == name]) for name in names}


def _latency(cases: list[dict[str, Any]]) -> dict[str, float]:
    millis = sorted(c["latency_ms"] for c in cases)
    p95 = millis[min(len(millis) - 1, round(0.95 * (len(millis) - 1)))]
    return {"median_ms": round(statistics.median(millis), 1), "p95_ms": p95}


def build(with_vectors: bool = True) -> dict[str, Any]:
    recordings, questions = _fixtures()
    with retriever_for(recordings, with_vectors) as retrieve:
        cases = [_ask(retrieve, question) for question in questions]
    return {
        "schema": SCHEMA,
        "date": datetime.now(UTC).date().isoformat(),
        "commit": _git("rev-parse", "--short", "HEAD") or "unknown",
        "uncommitted_changes": bool(_git("status", "--porcelain")),
        "what": "retrieval: is an expected recording among the top results for each question",
        "corpus": {
            "synthetic": True,
            "recordings": len(recordings),
            "questions": len(questions),
            "languages_of_recordings": sorted({r["language"] for r in recordings}),
        },
        "vector_index": "fake word-based (no meaning)" if with_vectors else "none (keyword only)",
        "models": "none: no embedding or language model is used in this run",
        "top": TOP,
        "overall": _share(cases),
        "by_question_language": _grouped(cases, "language"),
        "by_category": _grouped(cases, "category"),
        "unsupported_questions_that_returned_passages": [
            c["id"] for c in cases if c["hit_at_5"] is None and c["returned"]
        ],
        "latency": _latency(cases),
        "cases": cases,
        "limits": [
            "Synthetic questions and recordings; native speakers have not reviewed them.",
            "Most languages have one question, so a per-language score is a single case.",
            "The fake index matches shared words only: paraphrase questions are expected to miss.",
            "Answer quality and correct refusals are not measured here.",
        ],
    }


def write(report: dict[str, Any]) -> Path:
    index = "keyword" if report["vector_index"].startswith("none") else "fake-vectors"
    PUBLISHED.mkdir(parents=True, exist_ok=True)
    path = PUBLISHED / f"{report['date']}-retrieval-{index}-{report['commit']}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a published retrieval report")
    parser.add_argument("--keyword", action="store_true", help="keyword search only")
    report = build(with_vectors=not parser.parse_args().keyword)
    print(f"wrote {write(report)}")
    print(json.dumps({"overall": report["overall"], "latency": report["latency"]}, indent=2))


if __name__ == "__main__":
    main()
