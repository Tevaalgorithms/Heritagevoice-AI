"""Answer one question for one reader by running the question graph.

The reader is the server-built `Principal`; the graph checks it again before anything it found can
reach the answer. The result is shaped for the reader: citations carry the passage and its time in
the recording, never access labels or storage details.
"""

import re
from dataclasses import dataclass, field, replace
from typing import cast

from app.agents.answer_agent import INSUFFICIENT
from app.credits import Origin
from app.graph.state import WorkflowState
from app.graph.workflow import Agents, build_workflow
from app.models.evidence import Citation, Evidence, Turn
from app.models.records import path_text
from app.security.permissions import Principal

TIMES = re.compile(r"\?t=([0-9.]+)-([0-9.]+)$")
STATUSES = {"answered", "partial", "insufficient_evidence", "clarify", "refused"}
SOURCES_CHANGED = "sources_changed"


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
        connections=[path_text(path) for path in evidence.graph_paths],
    )


def _status(final: WorkflowState) -> str:
    status = final.get("status", "")
    return status if status in STATUSES else "insufficient_evidence"


@dataclass(frozen=True)
class Ask:
    """A question with what the page remembers: the chat so far and the answer language."""

    question: str
    language: str | None = None
    history: list[Turn] = field(default_factory=list)


def answer_question(ask: Ask, principal: Principal, agents: Agents) -> Outcome:
    """Run the graph. Authorization failures inside it raise `PermissionError`."""
    question = agents.rewrite(ask.question, ask.history) if agents.rewrite else ask.question
    start: WorkflowState = {"question": question}
    if ask.language:
        start["response_language"] = ask.language
    final = cast(WorkflowState, build_workflow(principal, agents=agents).invoke(start))
    outcome = Outcome(
        status=_status(final),
        answer=final.get("answer", ""),
        citations=[to_citation(item) for item in final.get("citations", [])],
        warnings=list(dict.fromkeys(final.get("warnings", []))),
    )
    return _with_origins(_still_valid(outcome, principal, agents), agents)


def _with_origins(outcome: Outcome, agents: Agents) -> Outcome:
    """Say when each cited recording was added and, only if its consent allows, who to credit."""
    if agents.origins is None or not outcome.citations:
        return outcome
    origins = agents.origins([c.recording_id for c in outcome.citations])
    return replace(outcome, citations=[_described(c, origins) for c in outcome.citations])


def _described(citation: Citation, origins: dict[str, Origin]) -> Citation:
    origin = origins.get(citation.recording_id)
    if origin is None:
        return citation
    return citation.model_copy(
        update={
            "added": origin.added,
            "heritage_kind": origin.heritage_kind,
            "language": origin.language,
            "credit": origin.credit,
        }
    )


def _still_valid(outcome: Outcome, principal: Principal, agents: Agents) -> Outcome:
    """Withdraw an answer whose sources can no longer be read (withdrawn, taken down, corrected
    while the question ran). The whole answer goes, as one bad source may be what it rests on."""
    if agents.still_readable is None or not outcome.citations:
        return outcome
    cited = [c.evidence_id for c in outcome.citations]
    if set(cited) <= agents.still_readable(cited, principal):
        return outcome
    warnings = [*outcome.warnings, SOURCES_CHANGED]
    return Outcome("insufficient_evidence", INSUFFICIENT, [], warnings)
