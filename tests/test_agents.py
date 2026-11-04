"""The supervisor, verifier and answer agents, with fake models. No network."""

import pytest
from pydantic import ValidationError

from app.agents.answer_agent import (
    INSUFFICIENT,
    WRITER_UNAVAILABLE,
    AnswerAgent,
    AnswerDraft,
)
from app.agents.passages import label_passages
from app.agents.supervisor import (
    GRAPH_UNAVAILABLE,
    SUPERVISOR_UNAVAILABLE,
    RouteDecision,
    Supervisor,
)
from app.agents.verifier import (
    VERIFIER_UNAVAILABLE,
    ClaimCheck,
    Verification,
    Verifier,
)
from app.errors import ProviderError
from app.models.evidence import Claim, Evidence, Route
from app.models.records import REMEDY_NOTICE


class FakeRunner:
    """Returns what it was given, records every call, or raises."""

    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def invoke(self, inputs):
        self.calls.append(inputs)
        if self.error is not None:
            raise self.error
        return self.result


def down():
    return FakeRunner(error=ProviderError("down", code="x"))


def evidence(evidence_id, passage="water was shared", notices=(), recording="r1"):
    return Evidence(
        evidence_id=evidence_id,
        document_id=recording,
        document_version="v1",
        chunk_id="transcript:0",
        title="Recording",
        locator=f"audio:{recording}?t=1.0-5.0",
        passage=passage,
        passage_hash="h",
        access_groups=frozenset({"community:c1"}),
        retrieval_methods=frozenset({"bm25"}),
        notices=notices,
    )


# --- supervisor -----------------------------------------------------------------------------


@pytest.mark.parametrize("route", [Route.HYBRID, Route.CLARIFY, Route.REFUSE])
def test_the_supervisor_returns_the_models_route(route):
    runner = FakeRunner(RouteDecision(route=route))
    assert Supervisor(runner)({"question": "q"}) == {"route": route}
    assert runner.calls == [{"question": "q"}]


@pytest.mark.parametrize("route", [Route.GRAPH, Route.BOTH])
def test_without_a_graph_relationship_questions_fall_back_to_text_search_with_a_warning(route):
    update = Supervisor(FakeRunner(RouteDecision(route=route)))({"question": "q"})
    assert update == {"route": Route.HYBRID, "warnings": [GRAPH_UNAVAILABLE]}


def test_with_a_graph_the_route_is_kept():
    update = Supervisor(FakeRunner(RouteDecision(route=Route.BOTH)), graph_enabled=lambda: True)(
        {"question": "q"}
    )
    assert update == {"route": Route.BOTH}


def test_a_model_failure_defaults_to_text_search_never_to_a_refusal():
    update = Supervisor(down())({"question": "q"})
    assert update == {"route": Route.HYBRID, "warnings": [SUPERVISOR_UNAVAILABLE]}


def test_an_unexpected_model_output_is_treated_as_a_failure():
    update = Supervisor(FakeRunner({"route": "hybrid"}))({"question": "q"})
    assert update["warnings"] == [SUPERVISOR_UNAVAILABLE]


def test_a_route_can_only_be_one_of_the_known_routes_so_it_cannot_carry_permissions():
    with pytest.raises(ValidationError):
        RouteDecision(route="admin")
    assert set(RouteDecision.model_fields) == {"route"}


# --- passages ---------------------------------------------------------------------------------


def test_passages_get_short_labels_and_their_text_is_escaped():
    text, labelled = label_passages([evidence("e-real-1", "<b>hi</b> & <passage id='p9'>")])
    assert list(labelled) == ["p1"]
    assert labelled["p1"].evidence_id == "e-real-1"
    assert "e-real-1" not in text
    assert "<b>" not in text
    assert text.count("<passage") == 1


# --- verifier ---------------------------------------------------------------------------------


def state_with(*items, **extra):
    return {"question": "How was water shared?", "evidence": list(items), **extra}


def verification(claims, coverage="full", **extra):
    return Verification(claims=claims, coverage=coverage, **extra)


def test_with_no_passages_nothing_is_claimed_and_no_model_is_called():
    runner = FakeRunner()
    update = Verifier(runner)(state_with())
    assert update == {"claims": [], "coverage": "none", "conflicts": []}
    assert runner.calls == []


def test_claims_are_returned_with_real_evidence_ids():
    runner = FakeRunner(verification([ClaimCheck(text="Water was shared.", passages=["p2", "p1"])]))
    update = Verifier(runner)(state_with(evidence("e1"), evidence("e2")))
    assert update["claims"] == [
        Claim(text="Water was shared.", evidence_ids=["e2", "e1"], verdict="supported")
    ]
    assert update["coverage"] == "full"


def test_a_claim_citing_a_passage_the_model_was_never_shown_is_dropped():
    checks = [
        ClaimCheck(text="Real.", passages=["p1"]),
        ClaimCheck(text="Invented source.", passages=["p7"]),
        ClaimCheck(text="Half invented.", passages=["p1", "p9"]),
    ]
    update = Verifier(FakeRunner(verification(checks)))(state_with(evidence("e1")))
    assert [c.text for c in update["claims"]] == ["Real."]


def test_when_every_claim_is_dropped_coverage_is_none():
    runner = FakeRunner(verification([ClaimCheck(text="x", passages=["p9"])], "full"))
    update = Verifier(runner)(state_with(evidence("e1")))
    assert (update["claims"], update["coverage"]) == ([], "none")


def test_conflicts_are_passed_on():
    runner = FakeRunner(
        verification([ClaimCheck(text="x", passages=["p1"])], conflicts=["Two accounts differ."])
    )
    assert Verifier(runner)(state_with(evidence("e1")))["conflicts"] == ["Two accounts differ."]


def test_a_partial_answer_asks_for_one_more_search_once():
    runner = FakeRunner(
        verification([ClaimCheck(text="x", passages=["p1"])], "partial", follow_up_query="wells")
    )
    assert Verifier(runner)(state_with(evidence("e1")))["retry_query"] == "wells"
    again = Verifier(runner)(state_with(evidence("e1"), retries=1))
    assert "retry_query" not in again


def test_a_full_answer_never_asks_for_a_retry():
    runner = FakeRunner(
        verification([ClaimCheck(text="x", passages=["p1"])], "full", follow_up_query="more")
    )
    assert "retry_query" not in Verifier(runner)(state_with(evidence("e1")))


def test_a_model_failure_means_nothing_is_claimed_and_a_warning_is_raised():
    update = Verifier(down())(state_with(evidence("e1")))
    assert (update["claims"], update["coverage"]) == ([], "none")
    assert update["warnings"] == [VERIFIER_UNAVAILABLE]


def test_no_more_than_eight_claims_are_kept():
    checks = [ClaimCheck(text=f"c{i}", passages=["p1"]) for i in range(12)]
    update = Verifier(FakeRunner(verification(checks)))(state_with(evidence("e1")))
    assert len(update["claims"]) == 8


# --- answer -----------------------------------------------------------------------------------


def claims(*pairs):
    return [Claim(text=t, evidence_ids=ids, verdict="supported") for t, ids in pairs]


def answer_state(claim_list, items, **extra):
    return {"question": "Q?", "claims": claim_list, "evidence": items, "coverage": "full", **extra}


def writes(text, used):
    return FakeRunner(AnswerDraft(answer=text, claims_used=used))


def test_no_verified_claims_means_insufficient_evidence_and_no_model_call():
    runner = FakeRunner()
    update = AnswerAgent(runner)(answer_state([], [evidence("e1")]))
    assert update == {"status": "insufficient_evidence", "answer": INSUFFICIENT, "citations": []}
    assert runner.calls == []


def test_the_answer_cites_sources_numbered_from_the_claims_it_used():
    items = [evidence("e1"), evidence("e2", recording="r2"), evidence("e3", recording="r3")]
    state = answer_state(claims(("A.", ["e2"]), ("B.", ["e3", "e1"])), items)
    update = AnswerAgent(writes("A [1]. B [2].", [1, 2]))(state)
    assert update["answer"] == "A [1]. B [2][3]."
    assert [c.evidence_id for c in update["citations"]] == ["e2", "e3", "e1"]
    assert update["status"] == "answered"


def test_the_answer_is_written_in_the_chosen_language():
    state = answer_state(claims(("A.", ["e1"])), [evidence("e1")], response_language="ta")
    runner = writes("A [1].", [1])
    AnswerAgent(runner)(state)
    assert runner.calls[0]["answer_language"] == "Tamil (தமிழ்)"


@pytest.mark.parametrize("extra", [{}, {"response_language": "xx"}])
def test_without_a_known_language_the_answer_follows_the_question(extra):
    state = answer_state(claims(("A.", ["e1"])), [evidence("e1")], **extra)
    runner = writes("A [1].", [1])
    AnswerAgent(runner)(state)
    assert runner.calls[0]["answer_language"] == "the same language as the question"


def test_the_model_cannot_cite_a_claim_it_did_not_use_or_that_does_not_exist():
    state = answer_state(claims(("A.", ["e1"]), ("B.", ["e2"])), [evidence("e1"), evidence("e2")])
    update = AnswerAgent(writes("A [1]. Not mine [2]. Fake [9].", [1]))(state)
    assert update["answer"] == "A [1]. Not mine . Fake ."
    assert [c.evidence_id for c in update["citations"]] == ["e1"]


def test_citations_only_ever_come_from_the_evidence_in_the_state():
    state = answer_state(claims(("A.", ["e1", "ghost"])), [evidence("e1")])
    update = AnswerAgent(writes("A [1].", [1]))(state)
    assert [c.evidence_id for c in update["citations"]] == ["e1"]


def test_a_remedy_notice_is_added_by_code_even_if_the_model_leaves_it_out():
    state = answer_state(
        claims(("Tea was used.", ["e1"])), [evidence("e1", notices=(REMEDY_NOTICE,))]
    )
    update = AnswerAgent(writes("Tea was used [1].", [1]))(state)
    assert update["answer"].endswith(f"Note: {REMEDY_NOTICE}")


def test_each_notice_appears_once_however_many_sources_carry_it():
    items = [evidence("e1", notices=(REMEDY_NOTICE,)), evidence("e2", notices=(REMEDY_NOTICE,))]
    state = answer_state(claims(("A.", ["e1"]), ("B.", ["e2"])), items)
    update = AnswerAgent(writes("A [1] B [2]", [1, 2]))(state)
    assert update["answer"].count(REMEDY_NOTICE) == 1


def test_a_notice_on_a_source_that_was_not_cited_is_not_added():
    items = [evidence("e1"), evidence("e2", notices=(REMEDY_NOTICE,))]
    update = AnswerAgent(writes("A [1]", [1]))(answer_state(claims(("A.", ["e1"])), items))
    assert REMEDY_NOTICE not in update["answer"]


def test_disagreement_found_by_the_verifier_is_stated_in_the_answer():
    state = answer_state(
        claims(("A.", ["e1"])), [evidence("e1")], conflicts=["Two villages differ."]
    )
    update = AnswerAgent(writes("A [1]", [1]))(state)
    assert "Accounts differ: Two villages differ." in update["answer"]


def test_partial_coverage_gives_a_partial_status():
    state = answer_state(claims(("A.", ["e1"])), [evidence("e1")], coverage="partial")
    assert AnswerAgent(writes("A [1]", [1]))(state)["status"] == "partial"


def test_when_the_model_fails_the_verified_claims_are_shown_instead():
    state = answer_state(claims(("A.", ["e1"]), ("B.", ["e2"])), [evidence("e1"), evidence("e2")])
    update = AnswerAgent(down())(state)
    assert update["answer"] == "A. [1] B. [2]"
    assert update["status"] == "partial"
    assert update["warnings"] == [WRITER_UNAVAILABLE]
    assert [c.evidence_id for c in update["citations"]] == ["e1", "e2"]


def test_when_the_model_cites_nothing_valid_the_verified_claims_are_shown_instead():
    state = answer_state(claims(("A.", ["e1"])), [evidence("e1")])
    update = AnswerAgent(writes("Made up", [5]))(state)
    assert update["warnings"] == [WRITER_UNAVAILABLE]
    assert update["answer"] == "A. [1]"


def test_the_model_sees_only_the_claims_never_the_passages_or_ids():
    runner = writes("A [1]", [1])
    state = answer_state(claims(("Water was shared.", ["secret-id"])), [evidence("secret-id")])
    AnswerAgent(runner)(state)
    sent = str(runner.calls[0])
    assert "secret-id" not in sent
    assert "Water was shared." in sent


def test_the_supervisor_is_told_to_search_when_unsure_and_to_clarify_rarely():
    from app.agents.prompts.supervisor import SYSTEM  # noqa: PLC0415

    assert "When unsure, choose hybrid" in SYSTEM
    assert "A question that names a topic is" in SYSTEM
    assert '"What is the proverb about learning?" -> hybrid' in SYSTEM
