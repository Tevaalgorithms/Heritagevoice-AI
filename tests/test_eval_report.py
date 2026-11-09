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


def test_a_real_embedding_model_is_named_in_the_report_and_needs_no_network_to_test(
    tmp_path, monkeypatch
):
    from app.fakes import FakeEmbedder  # noqa: PLC0415

    stand_in = r.RealEmbeddings("test-model", FakeEmbedder(32), 32)
    monkeypatch.setattr(r, "PUBLISHED", tmp_path)  # never write a test report to the real folder
    built = r.build(real=stand_in)
    assert "test-model" in built["vector_index"]
    assert built["models"] == {"embedding": "test-model", "language_model": None}
    assert not any("fake index" in limit for limit in built["limits"])
    assert r.write(built).name.split("-retrieval-")[1].startswith("real-embeddings")


def test_without_a_pinecone_key_a_real_run_stops_and_says_what_to_do(monkeypatch):
    from types import SimpleNamespace  # noqa: PLC0415

    monkeypatch.setattr(
        r, "Settings", lambda: SimpleNamespace(pinecone_api_key=None, embedding_dimension=1024)
    )
    with pytest.raises(SystemExit, match="PINECONE_API_KEY"):
        r.real_embeddings("multilingual-e5-large")
