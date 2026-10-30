"""Check what the retrieved passages can and cannot say, before any answer is written.

The model proposes claims and cites passage labels. We keep only claims whose labels all exist, so a
claim can never point at a source we did not show it. With no passages, or if the model is
unavailable, nothing is claimed: an unverified answer is never produced.
"""

import logging
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from app.agents.passages import label_passages
from app.config import IntegrationNotConfiguredError
from app.errors import ProviderError
from app.graph.state import StateUpdate, WorkflowState
from app.models.evidence import Claim, Evidence
from app.ports import Invoker

logger = logging.getLogger("heritagevoice.agents")
VERIFIER_UNAVAILABLE = "verification_unavailable"
MAX_CLAIMS = 8
MAX_RETRIES = 1


class ClaimCheck(BaseModel):
    """A statement the passages support, with the labels of the passages that support it."""

    text: Annotated[str, Field(min_length=1, max_length=500)]
    passages: Annotated[list[str], Field(min_length=1, max_length=6)]


class Verification(BaseModel):
    """What the verifier found: supported claims, how well they cover the question, conflicts."""

    claims: Annotated[list[ClaimCheck], Field(max_length=12)]
    coverage: Literal["full", "partial", "none"]
    conflicts: Annotated[list[Annotated[str, Field(max_length=300)]], Field(max_length=5)] = []
    follow_up_query: Annotated[str | None, Field(max_length=200)] = None


def _verification(result: Any) -> Verification:
    if not isinstance(result, Verification):
        raise ProviderError("unexpected verification output", code="verifier")
    return result


def _supported(checks: list[ClaimCheck], labelled: dict[str, Evidence]) -> list[Claim]:
    """Claims whose every cited label is real, with real evidence IDs. Others are dropped."""
    claims = []
    for check in checks:
        if all(label in labelled for label in check.passages):
            ids = list(dict.fromkeys(labelled[label].evidence_id for label in check.passages))
            claims.append(Claim(text=check.text, evidence_ids=ids, verdict="supported"))
    return claims[:MAX_CLAIMS]


def _retry(verification: Verification, state: WorkflowState) -> StateUpdate:
    """Ask for one more search, once, if the passages do not cover the question."""
    allowed = state.get("retries", 0) < MAX_RETRIES
    wanted = verification.coverage != "full" and verification.follow_up_query
    return {"retry_query": verification.follow_up_query} if allowed and wanted else {}


class Verifier:
    """Extracts supported claims from the passages and judges coverage."""

    def __init__(self, runner: Invoker) -> None:
        self._runner = runner

    def __call__(self, state: WorkflowState) -> StateUpdate:
        evidence = state.get("evidence", [])
        if not evidence:
            return {"claims": [], "coverage": "none", "conflicts": []}
        passages, labelled = label_passages(evidence)
        try:
            found = _verification(
                self._runner.invoke({"question": state["question"], "passages": passages})
            )
        except ProviderError:
            return {
                "claims": [],
                "coverage": "none",
                "conflicts": [],
                "warnings": [VERIFIER_UNAVAILABLE],
            }
        claims = _supported(found.claims, labelled)
        coverage = found.coverage if claims else "none"
        return {
            "claims": claims,
            "coverage": coverage,
            "conflicts": found.conflicts,
            **_retry(found.model_copy(update={"coverage": coverage}), state),
        }


def verify(state: WorkflowState) -> StateUpdate:
    """The default node, used until the service wires in a `Verifier` with a model."""
    raise IntegrationNotConfiguredError("Claim support verification is not wired to a model yet")
