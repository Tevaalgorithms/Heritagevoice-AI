"""Retrieval evaluation as a LangSmith experiment, with results per language and per question type.

    uv run python -m evals.langsmith_eval --local     # no account: run it and print the table
    uv run python -m evals.langsmith_eval             # upload the dataset and run an experiment

The questions and recordings are the SYNTHETIC development fixtures plus the synthetic demo library;
nothing from a real community is ever read or sent. The default run needs `LANGSMITH_API_KEY` in
your environment (never in a file in this repository). Each experiment records the commit, the
corpus and the kind of vector index, so two experiments can be compared in LangSmith.

What is measured: for each answerable question, did retrieval return a recording the people who
labelled the fixtures expect, in the top results (`hit_at_5`), and how high (`reciprocal_rank`).
Unsupported questions get no retrieval score: refusing to answer them is the verifier's job, which
needs language-model calls and is measured separately.

The vector index here is a fake word-based one (see `evals.retrieval_check`), so a score shows the
plumbing and keyword search work in every language, not how well a multilingual embedding model
understands meaning. Run `evals.embedding_bakeoff` for that.
"""

import argparse
import os
import subprocess
import sys
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from app.demo_seed import as_fixture, load_corpus
from app.evaluation import load_fixtures
from app.models.evidence import Evidence
from app.retrieval_evaluation import TOP, distinct_recordings, first_rank, recording_of
from evals.retrieval_check import FIXTURES, retriever_for

DATASET = "heritagevoice-retrieval-synthetic"
Row = dict[str, Any]


def _fixtures() -> tuple[list[Row], list[Row]]:
    """Every synthetic recording and question: the development set, then the demo library."""
    dev_recordings, dev_questions = load_fixtures(FIXTURES)
    demo = load_corpus()
    recordings = [*dev_recordings, *(as_fixture(r) for r in demo["recordings"])]
    questions = [
        *({**q, "corpus": "dev"} for q in dev_questions),
        *({**q, "corpus": "demo"} for q in demo["questions"]),
    ]
    return recordings, questions


def examples(questions: list[Row]) -> list[Row]:
    """LangSmith examples: what is asked, what should come back, and labels to slice results by."""
    return [
        {
            "inputs": {"question": q["question"]},
            "outputs": {
                "recordings": sorted({recording_of(s) for s in q["expected_sources"]}),
                "answerable": q["answerable"],
            },
            "metadata": {k: q[k] for k in ("id", "category", "language", "corpus")},
        }
        for q in questions
    ]


def make_target(retrieve: Callable[[str], list[Evidence]]) -> Callable[[Row], Row]:
    """The thing under test: a question in, the recordings retrieval returned, best first."""

    def target(inputs: Row) -> Row:
        return {"recordings": distinct_recordings(retrieve(inputs["question"]))}

    return target


def _rank(outputs: Row, reference: Row) -> int | None:
    return first_rank(outputs["recordings"], set(reference["recordings"]))


def hit_at_5(outputs: Row, reference_outputs: Row) -> Row:
    """1 if an expected recording is among the top results (not scored for unsupported ones)."""
    if not reference_outputs["answerable"]:
        return {"key": "hit_at_5", "score": None, "comment": "unsupported question"}
    rank = _rank(outputs, reference_outputs)
    return {"key": "hit_at_5", "score": int(rank is not None and rank <= TOP)}


def reciprocal_rank(outputs: Row, reference_outputs: Row) -> Row:
    """1 for first place, 0.5 for second, and so on; 0 if it was not returned."""
    if not reference_outputs["answerable"]:
        return {"key": "reciprocal_rank", "score": None, "comment": "unsupported question"}
    rank = _rank(outputs, reference_outputs)
    return {"key": "reciprocal_rank", "score": 0.0 if rank is None else 1.0 / rank}


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summary(runs: list[Any], examples_: list[Any]) -> Row:
    """Whole-experiment numbers: recall@5 and mean reciprocal rank overall, and recall@5 for each
    language. Each is the share of answerable questions, so read it with the count beside it."""
    hits: dict[str, list[float]] = defaultdict(list)
    ranks: list[float] = []
    for run, example in zip(runs, examples_, strict=True):
        if not example.outputs["answerable"]:
            continue
        hit = hit_at_5(run.outputs, example.outputs)["score"]
        rr = reciprocal_rank(run.outputs, example.outputs)["score"]
        hits["all"].append(hit)
        hits[example.metadata["language"]].append(hit)
        ranks.append(rr)
    results = [{"key": "recall_at_5", "score": _mean(hits["all"])}]
    results.append({"key": "mrr", "score": _mean(ranks)})
    for language in sorted(set(hits) - {"all"}):
        results.append(
            {
                "key": f"recall_at_5_{language}",
                "score": _mean(hits[language]),
                "comment": f"{len(hits[language])} questions",
            }
        )
    return {"results": results}


class _Local:
    """A run or example reduced to what the evaluators read, for a run that uploads nothing."""

    def __init__(self, outputs: Row, metadata: Row | None = None) -> None:
        self.outputs = outputs
        self.metadata = metadata or {}


def run_local(with_vectors: bool = True) -> Row:
    """Run everything in this process and return the summary numbers."""
    recordings, questions = _fixtures()
    cases = examples(questions)
    with retriever_for(recordings, with_vectors) as retrieve:
        target = make_target(retrieve)
        runs = [_Local(target(case["inputs"])) for case in cases]
    pairs = [_Local(case["outputs"], case["metadata"]) for case in cases]
    return {r["key"]: (r["score"], r.get("comment")) for r in summary(runs, pairs)["results"]}


def _commit() -> str:
    done = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
    )
    return done.stdout.strip() or "unknown"


def _ensure_dataset(client: Any, cases: list[Row]) -> None:
    """Create the dataset on first use. An existing one is left alone, so past experiments keep the
    questions they were run on; change DATASET when the questions change."""
    if client.has_dataset(dataset_name=DATASET):
        return
    dataset = client.create_dataset(
        DATASET, description="SYNTHETIC multilingual retrieval questions. No community data."
    )
    client.create_examples(dataset_id=dataset.id, examples=cases)


def run_experiment(with_vectors: bool = True) -> str:
    """Upload the dataset if needed and run one experiment. Returns the experiment's name."""
    from langsmith import Client, evaluate  # noqa: PLC0415  (only needed with an account)

    recordings, questions = _fixtures()
    cases = examples(questions)
    client = Client()
    _ensure_dataset(client, cases)
    vectors = "fake-word-vectors" if with_vectors else "keyword-only"
    with retriever_for(recordings, with_vectors) as retrieve:
        result = evaluate(
            make_target(retrieve),
            data=DATASET,
            evaluators=[hit_at_5, reciprocal_rank],
            summary_evaluators=[summary],
            experiment_prefix=f"retrieval-{vectors}",
            metadata={"commit": _commit(), "vectors": vectors, "top": TOP, "synthetic": True},
            max_concurrency=1,
            client=client,
        )
    return str(result.experiment_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval, locally or in LangSmith")
    parser.add_argument("--local", action="store_true", help="no LangSmith: print the numbers")
    parser.add_argument("--keyword", action="store_true", help="keyword search only")
    args = parser.parse_args()
    if args.local:
        for key, (score, comment) in run_local(not args.keyword).items():
            shown = "n/a" if score is None else f"{score:.2f}"
            print(f"{key:18} {shown:>5}  {comment or ''}")
        return
    if not os.environ.get("LANGSMITH_API_KEY"):
        sys.exit("Set LANGSMITH_API_KEY in your shell (not in a file), or use --local.")
    print(f"experiment: {run_experiment(not args.keyword)}")


if __name__ == "__main__":
    main()
