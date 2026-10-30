"""Query variants, fusion of searches, and choosing the final passages (all pure functions)."""

import pytest

from app.models.evidence import Evidence
from app.retrieval.fusion import RRF_K, fuse_branches
from app.retrieval.query import normalize_query
from app.retrieval.selection import SelectionLimits, estimate_tokens, select_passages


def evidence(evidence_id, recording="r1", passage="some words here", method="bm25"):
    return Evidence(
        evidence_id=evidence_id,
        document_id=recording,
        document_version="v1",
        chunk_id=f"transcript:{evidence_id}",
        title="Recording",
        locator=f"audio:{recording}?t=0-1",
        passage=passage,
        passage_hash="h",
        access_groups=frozenset({"community:c1"}),
        retrieval_methods=frozenset({method}),
    )


# --- the question ---------------------------------------------------------------------------


def test_the_question_as_typed_is_always_searched_first():
    assert normalize_query("  Who sang?  ").variants[0] == "Who sang?"
    assert normalize_query("  Who sang?  ").original == "Who sang?"


def test_a_clean_question_has_exactly_one_form():
    assert normalize_query("water").variants == ("water",)


def test_extra_spaces_and_unicode_forms_become_one_extra_variant():
    decomposed = "café   water"  # 'e' + combining acute, and a run of spaces
    variants = normalize_query(decomposed).variants
    assert variants[0] == decomposed
    assert "café water" in variants


def test_invisible_joiners_are_removed_in_a_variant_but_never_from_the_original():
    typed = "வணக்‍கம்"
    variants = normalize_query(typed).variants
    assert variants[0] == typed
    assert "வணக்கம்" in variants


def test_variants_never_repeat_and_an_empty_question_has_none():
    assert len(set(normalize_query("a  b").variants)) == len(normalize_query("a  b").variants)
    assert normalize_query("   ").variants == ()


# --- fusing searches -----------------------------------------------------------------------


def test_a_passage_found_by_two_searches_appears_once_with_both_methods_and_ranks():
    keyword = [evidence("a", method="bm25"), evidence("b", method="bm25")]
    vector = [evidence("b", method="vector"), evidence("c", method="vector")]
    hits = fuse_branches({"bm25": keyword, "vector": vector})
    by_id = {h.evidence.evidence_id: h for h in hits}
    assert sorted(by_id) == ["a", "b", "c"]
    assert by_id["b"].evidence.retrieval_methods == {"bm25", "vector"}
    assert dict(by_id["b"].ranks) == {"bm25": 2, "vector": 1}
    assert dict(by_id["a"].ranks) == {"bm25": 1}


def test_a_passage_both_searches_rank_highly_beats_one_found_by_a_single_search():
    keyword = [evidence("only-keyword"), evidence("both")]
    vector = [evidence("both", method="vector"), evidence("only-vector", method="vector")]
    ids = [h.evidence.evidence_id for h in fuse_branches({"bm25": keyword, "vector": vector})]
    assert ids[0] == "both"


def test_the_fused_score_is_the_sum_of_reciprocal_ranks():
    hits = fuse_branches({"bm25": [evidence("a")], "vector": [evidence("a", method="vector")]})
    assert hits[0].score == pytest.approx(2 / (RRF_K + 1))


def test_ties_break_by_evidence_id_so_the_order_is_stable():
    hits = fuse_branches({"bm25": [evidence("b")], "vector": [evidence("a", method="vector")]})
    assert [h.evidence.evidence_id for h in hits] == ["a", "b"]


def test_a_repeat_inside_one_search_counts_once_at_its_best_position():
    hits = fuse_branches({"bm25": [evidence("a"), evidence("b"), evidence("a")]})
    assert [(h.evidence.evidence_id, dict(h.ranks)["bm25"]) for h in hits] == [("a", 1), ("b", 2)]


def test_fusing_nothing_gives_nothing():
    assert fuse_branches({}) == []
    assert fuse_branches({"bm25": [], "vector": []}) == []


# --- choosing passages ---------------------------------------------------------------------


def hits(*items):
    return fuse_branches({"bm25": list(items)})


def test_at_most_eight_passages_are_kept_best_first():
    many = [evidence(f"e{i:02d}", recording=f"r{i}") for i in range(12)]
    chosen = select_passages(hits(*many))
    assert [h.evidence.evidence_id for h in chosen] == [f"e{i:02d}" for i in range(8)]


def test_no_more_than_two_passages_come_from_one_recording():
    same = [evidence(f"e{i}", recording="r1") for i in range(5)]
    other = evidence("x", recording="r2")
    chosen = select_passages(hits(*same, other))
    assert [h.evidence.evidence_id for h in chosen] == ["e0", "e1", "x"]


def test_the_token_budget_skips_a_passage_that_does_not_fit_but_keeps_smaller_ones():
    big = "word " * 400
    items = [evidence("a", "r1"), evidence("b", "r2", passage=big), evidence("c", "r3")]
    chosen = select_passages(hits(*items), SelectionLimits(token_budget=100))
    assert [h.evidence.evidence_id for h in chosen] == ["a", "c"]


def test_the_best_passage_is_kept_even_if_it_alone_exceeds_the_budget():
    chosen = select_passages(
        hits(evidence("a", passage="word " * 1000)), SelectionLimits(token_budget=10)
    )
    assert [h.evidence.evidence_id for h in chosen] == ["a"]


def test_nothing_in_means_nothing_out():
    assert select_passages([]) == []


def test_tamil_is_counted_as_larger_than_the_same_number_of_latin_letters():
    assert estimate_tokens("தண்ணீர்") > estimate_tokens("water")
    assert estimate_tokens("") == 1
