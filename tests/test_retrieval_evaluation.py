"""The retrieval measurement itself, and a regression check on the fixtures.

The fixture run uses a fake vector index that matches on shared words. It proves the pieces fit
together (keyword + vector + fusion + selection, with permissions); it says nothing about how well a
real multilingual model finds meaning across languages. That needs `evals.embedding_bakeoff`.
"""

import pytest

from app.models.evidence import Evidence
from app.retrieval_evaluation import (
    CaseResult,
    distinct_recordings,
    first_rank,
    recording_of,
    run_cases,
    summarize,
)
from evals.retrieval_check import run


def evidence(recording):
    return Evidence(
        evidence_id=f"{recording}:e",
        document_id=recording,
        document_version="v1",
        chunk_id="transcript:0",
        title="t",
        locator="audio:x?t=0-1",
        passage="p",
        passage_hash="h",
        access_groups=frozenset({"community:c1"}),
        retrieval_methods=frozenset({"bm25"}),
    )


def question(qid, expected, category="exact_term"):
    return {
        "id": qid,
        "category": category,
        "language": "en",
        "question": qid,
        "expected_sources": expected,
    }


def test_a_source_names_its_recording():
    assert recording_of("rec-01:s3") == "rec-01"


def test_recordings_are_listed_once_in_first_seen_order():
    assert distinct_recordings([evidence("b"), evidence("a"), evidence("b")]) == ["b", "a"]


def test_the_rank_is_the_first_expected_recording_counted_from_one():
    assert first_rank(["x", "y", "z"], {"z", "y"}) == 2
    assert first_rank(["x"], {"z"}) is None
    assert first_rank([], {"z"}) is None


def test_each_question_gets_its_rank_and_what_came_back():
    returns = {"q1": [evidence("b"), evidence("a")], "q2": [evidence("c")]}
    cases = [question("q1", ["a:s1", "a:s2"]), question("q2", ["z:s1"])]
    results = run_cases(lambda text: returns[text], cases)
    assert [(r.question_id, r.rank, r.returned) for r in results] == [
        ("q1", 2, ("b", "a")),
        ("q2", None, ("c",)),
    ]
    assert results[0].expected == ("a",)


def result(qid, rank, **overrides):
    fields = {"category": "exact_term", "expected": ("a",), "returned": ("a",), **overrides}
    return CaseResult(qid, fields["category"], "en", fields["expected"], rank, fields["returned"])


def test_the_summary_counts_hits_within_the_top_five_by_category():
    summary = summarize(
        [
            result("q1", 1),
            result("q2", 5),
            result("q3", 6),
            result("q4", None, category="paraphrase"),
        ]
    )
    assert summary["by_category"]["exact_term"] == {
        "cases": 3,
        "found_in_top": 2,
        "ranks": {"q1": 1, "q2": 5, "q3": 6},
    }
    assert summary["by_category"]["all"]["cases"] == 4
    assert summary["by_category"]["paraphrase"]["found_in_top"] == 0


def test_unsupported_questions_are_reported_apart_from_the_score():
    summary = summarize(
        [result("q1", 1), result("q11", None, category="unsupported", expected=(), returned=("a",))]
    )
    assert summary["by_category"]["all"]["cases"] == 1
    assert summary["unsupported_questions_that_returned_passages"] == ["q11"]


@pytest.fixture(scope="module")
def with_vectors():
    return run(with_vectors=True)


@pytest.fixture(scope="module")
def keyword_only():
    return run(with_vectors=False)


def found(report, category="all"):
    return report["by_category"][category]["found_in_top"]


def test_every_exact_term_question_finds_its_source_by_keyword_alone(keyword_only):
    assert found(keyword_only, "exact_term") == 4


def test_fixtures_every_answerable_question_finds_its_source_in_the_top_five(with_vectors):
    assert found(with_vectors) == with_vectors["by_category"]["all"]["cases"] == 10


def test_adding_the_vector_search_never_loses_a_source_keyword_search_found(
    keyword_only, with_vectors
):
    for qid, rank in keyword_only["by_category"]["all"]["ranks"].items():
        if rank is not None and rank <= 5:
            assert with_vectors["by_category"]["all"]["ranks"][qid] <= 5


def test_fusion_rescues_a_paraphrase_that_shares_no_words_with_its_passage(
    keyword_only, with_vectors
):
    assert keyword_only["by_category"]["paraphrase"]["ranks"]["q06"] is None
    assert with_vectors["by_category"]["paraphrase"]["ranks"]["q06"] is not None
