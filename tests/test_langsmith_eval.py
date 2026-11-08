"""The LangSmith evaluation scores what retrieval returns, and runs with no account or network."""

import json
from types import SimpleNamespace

import pytest

from evals import langsmith_eval as ev
from evals.retrieval_check import FIXTURES

ANSWERABLE = {"recordings": ["r1"], "answerable": True}
UNSUPPORTED = {"recordings": [], "answerable": False}


def test_only_synthetic_fixtures_are_ever_sent():
    notes = [
        json.loads((FIXTURES / "recordings.json").read_text())["_note"],
        json.loads((FIXTURES / "questions.json").read_text())["_note"],
        ev.load_corpus()["_note"],
    ]
    assert all("SYNTHETIC" in note for note in notes)


def test_every_question_becomes_an_example_labelled_for_slicing():
    _, questions = ev._fixtures()
    cases = ev.examples(questions)
    assert len(cases) == len(questions) == 28
    for case in cases:
        assert set(case["metadata"]) == {"id", "category", "language", "corpus"}
        assert case["inputs"]["question"]
        assert bool(case["outputs"]["recordings"]) == case["outputs"]["answerable"]
    assert {c["metadata"]["corpus"] for c in cases} == {"dev", "demo"}


@pytest.mark.parametrize(
    ("returned", "hit", "rr"),
    [
        (["r1", "x"], 1, 1.0),
        (["x", "r1"], 1, 0.5),
        (["x", "y"], 0, 0.0),
        (["a"] * 5 + ["r1"], 0, 1 / 6),
    ],
)
def test_hit_and_reciprocal_rank_for_an_answerable_question(returned, hit, rr):
    outputs = {"recordings": returned}
    assert ev.hit_at_5(outputs, ANSWERABLE)["score"] == hit
    assert ev.reciprocal_rank(outputs, ANSWERABLE)["score"] == pytest.approx(rr)


def test_an_unsupported_question_gets_no_retrieval_score():
    outputs = {"recordings": ["r1"]}
    assert ev.hit_at_5(outputs, UNSUPPORTED)["score"] is None
    assert ev.reciprocal_rank(outputs, UNSUPPORTED)["score"] is None


def test_the_summary_counts_answerable_questions_per_language_and_skips_unsupported():
    def pair(language, returned, reference):
        meta = {"language": language}
        return SimpleNamespace(outputs={"recordings": returned}), SimpleNamespace(
            outputs=reference, metadata=meta
        )

    pairs = [
        pair("ta", ["r1"], ANSWERABLE),
        pair("ta", ["x"], ANSWERABLE),
        pair("hi", ["r1"], ANSWERABLE),
        pair("en", ["r1"], UNSUPPORTED),
    ]
    runs, cases = zip(*pairs, strict=True)
    scores = {r["key"]: r["score"] for r in ev.summary(list(runs), list(cases))["results"]}
    assert scores["recall_at_5"] == pytest.approx(2 / 3)
    assert scores["recall_at_5_ta"] == 0.5
    assert scores["recall_at_5_hi"] == 1.0
    assert "recall_at_5_en" not in scores


def test_a_local_run_covers_every_demo_language_with_no_account():
    scores = ev.run_local()
    for language in ("ta", "hi", "te", "ml", "bn", "fr", "es", "pt", "en"):
        assert scores[f"recall_at_5_{language}"][0] is not None
    assert scores["recall_at_5"][0] > 0.9


def test_without_a_key_the_experiment_run_stops_and_says_what_to_do(monkeypatch):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["langsmith_eval"])
    with pytest.raises(SystemExit, match="LANGSMITH_API_KEY"):
        ev.main()
