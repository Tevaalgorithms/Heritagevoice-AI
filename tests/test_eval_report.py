"""The published retrieval report says what was run, shows its denominators, stays synthetic."""

import json

import pytest

from evals import report as r


@pytest.fixture(scope="module")
def built():
    return r.build()


def test_the_report_says_what_was_run_and_that_it_is_synthetic(built):
    assert built["corpus"]["synthetic"] is True
    assert built["corpus"]["questions"] == len(built["cases"]) == 28
    assert "fake" in built["vector_index"]
    assert built["models"].startswith("none")
    assert built["limits"]


def test_every_total_shows_how_many_questions_it_is_out_of(built):
    overall = built["overall"]
    assert overall["answerable_questions"] == 24
    assert 0 <= overall["found_in_top_5"] <= overall["answerable_questions"]
    per_language = built["by_question_language"]
    assert sum(v["answerable_questions"] for v in per_language.values()) == 24
    assert {"ta", "hi", "te", "ml", "bn", "fr", "es", "pt", "en"} <= set(per_language)


def test_unsupported_questions_are_listed_but_never_scored(built):
    unsupported = [c for c in built["cases"] if not c["expected"]]
    assert len(unsupported) == 4
    assert all(c["hit_at_5"] is None and c["rank"] is None for c in unsupported)


def test_the_report_is_written_under_the_published_folder(built, tmp_path, monkeypatch):
    monkeypatch.setattr(r, "PUBLISHED", tmp_path)
    path = r.write(built)
    assert path.parent == tmp_path
    assert path.name.startswith(built["date"])
    assert built["commit"] in path.name
    assert json.loads(path.read_text(encoding="utf-8"))["overall"] == built["overall"]


def test_the_latency_summary_has_a_median_and_a_slow_tail(built):
    assert 0 <= built["latency"]["median_ms"] <= built["latency"]["p95_ms"]
