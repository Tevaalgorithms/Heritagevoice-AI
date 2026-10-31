"""Write the answer from verified claims only, then build its citations in code.

The model writes prose and cites claim numbers. We never trust its sources: the citations are the
evidence that the cited claims already carry, renumbered as `[1]`, `[2]` for the reader. Notices
(for example the remedy notice) and any disagreement the verifier found are added by us, so a model
cannot leave them out. With no verified claims there is no model call and no invented answer; if the
model fails, the verified claims themselves are shown.
"""

import logging
import re
from typing import Annotated, Any

from pydantic import BaseModel, Field

from app.config import IntegrationNotConfiguredError
from app.errors import ProviderError
from app.graph.state import StateUpdate, WorkflowState
from app.languages import BY_CODE
from app.models.evidence import Claim, Evidence
from app.ports import Invoker

logger = logging.getLogger("heritagevoice.agents")
WRITER_UNAVAILABLE = "answer_writer_unavailable"
INSUFFICIENT = "The recordings you can read do not contain enough to answer this question."
FALLBACK_CLAIMS = 3
SAME_LANGUAGE = "the same language as the question"
MARKER = re.compile(r"\[(\d+)\]")


class AnswerDraft(BaseModel):
    """The model's prose, and which of the numbered claims it relied on."""

    answer: Annotated[str, Field(min_length=1, max_length=4000)]
    claims_used: Annotated[list[int], Field(max_length=12)]


def _language_name(code: str | None) -> str:
    """The language to write in, as the model should read it. Unknown or unset: the question's."""
    language = BY_CODE.get(code or "")
    return f"{language.name} ({language.native_name})" if language else SAME_LANGUAGE


def _draft(result: Any) -> AnswerDraft:
    if not isinstance(result, AnswerDraft):
        raise ProviderError("unexpected answer output", code="answer")
    return result


def _number_one(
    evidence_id: str, by_id: dict[str, Evidence], numbers: dict[str, int], cited: list[Evidence]
) -> None:
    """Number a source the first time it is cited."""
    if evidence_id in by_id and evidence_id not in numbers:
        numbers[evidence_id] = len(cited) + 1
        cited.append(by_id[evidence_id])


def _number_sources(
    claim: Claim, by_id: dict[str, Evidence], numbers: dict[str, int], cited: list[Evidence]
) -> list[int]:
    """Give each of the claim's sources a number; return the numbers that apply to this claim."""
    for evidence_id in claim.evidence_ids:
        _number_one(evidence_id, by_id, numbers, cited)
    return [numbers[i] for i in claim.evidence_ids if i in numbers]


def _sources(
    claims: list[Claim], used: list[int], by_id: dict[str, Evidence]
) -> tuple[list[Evidence], dict[int, list[int]]]:
    """The cited evidence in order of first use, and each used claim's source numbers."""
    numbers: dict[str, int] = {}
    cited: list[Evidence] = []
    by_claim = {i: _number_sources(claims[i - 1], by_id, numbers, cited) for i in used}
    return cited, by_claim


def _renumbered(text: str, by_claim: dict[int, list[int]]) -> str:
    """Replace claim markers with source markers; drop any marker that is not a used claim."""

    def swap(match: re.Match[str]) -> str:
        return "".join(f"[{n}]" for n in by_claim.get(int(match.group(1)), []))

    return MARKER.sub(swap, text).strip()


def _valid_used(draft: AnswerDraft, claim_count: int) -> list[int]:
    return sorted({n for n in draft.claims_used if 1 <= n <= claim_count})


def _notices(citations: list[Evidence]) -> list[str]:
    return list(dict.fromkeys(n for item in citations for n in item.notices))


def _extras(citations: list[Evidence], conflicts: list[str]) -> str:
    """Lines we add ourselves: where accounts differ, and every notice that must travel along."""
    lines = [f"Accounts differ: {c}" for c in conflicts]
    lines += [f"Note: {n}" for n in _notices(citations)]
    return "\n\n" + "\n".join(lines) if lines else ""


def _fallback(claims: list[Claim]) -> tuple[str, list[int]]:
    """Without a model: the first verified claims, each marked with its own number."""
    used = list(range(1, min(len(claims), FALLBACK_CLAIMS) + 1))
    return " ".join(f"{claims[i - 1].text} [{i}]" for i in used), used


def _status(coverage: str | None, warnings: list[str]) -> str:
    return "answered" if coverage == "full" and not warnings else "partial"


class AnswerAgent:
    """Turns verified claims into a cited answer, or says there is not enough."""

    def __init__(self, runner: Invoker) -> None:
        self._runner = runner

    def __call__(self, state: WorkflowState) -> StateUpdate:
        claims = state.get("claims", [])
        if not claims:
            return {"status": "insufficient_evidence", "answer": INSUFFICIENT, "citations": []}
        return self._answer(state, claims)

    def _answer(self, state: WorkflowState, claims: list[Claim]) -> StateUpdate:
        language = _language_name(state.get("response_language"))
        text, used, warnings = self._write(state["question"], claims, language)
        by_id = {item.evidence_id: item for item in state.get("evidence", [])}
        citations, by_claim = _sources(claims, used, by_id)
        answer = _renumbered(text, by_claim) + _extras(citations, state.get("conflicts", []))
        update: StateUpdate = {
            "status": _status(state.get("coverage"), warnings),
            "answer": answer,
            "citations": citations,
        }
        update.update({"warnings": warnings} if warnings else {})
        return update

    def _write(
        self, question: str, claims: list[Claim], language: str
    ) -> tuple[str, list[int], list[str]]:
        numbered = "\n".join(f"[{i}] {claim.text}" for i, claim in enumerate(claims, start=1))
        inputs = {"question": question, "claims": numbered, "answer_language": language}
        try:
            draft = _draft(self._runner.invoke(inputs))
        except ProviderError:
            return (*_fallback(claims), [WRITER_UNAVAILABLE])
        used = _valid_used(draft, len(claims))
        return (draft.answer, used, []) if used else (*_fallback(claims), [WRITER_UNAVAILABLE])


def synthesize(state: WorkflowState) -> StateUpdate:
    """The default node, used until the service wires in an `AnswerAgent` with a model."""
    raise IntegrationNotConfiguredError("Answer synthesis is not wired to a model yet")
