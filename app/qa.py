"""Answer one question for one reader by running the question graph.

The reader is the server-built `Principal`; the graph checks it again before anything it found can
reach the answer. The result is shaped for the reader: citations carry the passage and its time in
the recording, never access labels or storage details.
"""

import re
from dataclasses import dataclass
from typing import cast

from app.graph.state import WorkflowState
from app.graph.workflow import Agents, build_workflow
from app.models.evidence import Citation, Evidence
from app.security.permissions import Principal

TIMES = re.compile(r"\?t=([0-9.]+)-([0-9.]+)$")
STATUSES = {"answered", "partial", "insufficient_evidence", "clarify", "refused"}


@dataclass(frozen=True)
class Outcome:
    """What a question produced."""

    status: str
    answer: str
    citations: list[Citation]
    warnings: list[str]


def _times(locator: str) -> tuple[float, float]:
    match = TIMES.search(locator)
    return (float(match.group(1)), float(match.group(2))) if match else (0.0, 0.0)


def to_citation(evidence: Evidence) -> Citation:
    start, end = _times(evidence.locator)
    return Citation(
        evidence_id=evidence.evidence_id,
        recording_id=evidence.document_id,
        title=evidence.title,
        passage=evidence.passage,
        start_s=start,
        end_s=end,
        notices=list(evidence.notices),
    )


def _status(final: WorkflowState) -> str:
    status = final.get("status", "")
    return status if status in STATUSES else "insufficient_evidence"


def answer_question(question: str, principal: Principal, agents: Agents) -> Outcome:
    """Run the graph. Authorization failures inside it raise `PermissionError`."""
    final = cast(
        WorkflowState, build_workflow(principal, agents=agents).invoke({"question": question})
    )
    return Outcome(
        status=_status(final),
        answer=final.get("answer", ""),
        citations=[to_citation(item) for item in final.get("citations", [])],
        warnings=list(dict.fromkeys(final.get("warnings", []))),
    )
