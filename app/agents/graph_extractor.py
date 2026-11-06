"""Propose knowledge-graph relationships from an approved transcript.

The model only proposes. Everything it returns is checked here (a real segment, a known relation,
sensible names, no repeats) and stored as *pending*; nothing reaches the graph or an answer until a
person approves it. The same text always yields the same assertion IDs, so running again adds only
what is new and never overwrites a decision.
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from app.errors import ProviderError
from app.models.records import GraphAssertion, Relation, ReviewState
from app.models.transcript import Segment
from app.ports import Invoker

logger = logging.getLogger("heritagevoice.agents")
EXTRACTION = "extraction"
BATCH_SIZE = 40
MAX_PER_RECORDING = 200
MAX_NAME = 200
UNKNOWN_SPEAKER = "unknown"
PROPOSABLE = frozenset(Relation) - {Relation.SUPPORTED_BY}  # support links are added by the system


class Proposal(BaseModel):
    """One relationship the model proposes, tied to the segment that says it."""

    subject: str
    relation: Relation
    object: str
    segment_id: str
    confidence: float = Field(default=0.5, ge=0, le=1)


class Proposals(BaseModel):
    """The structured answer the model must return for a batch of segments."""

    assertions: list[Proposal] = []


@dataclass(frozen=True)
class Source:
    """What is being read: an approved transcript and the policy it was consented under."""

    recording_id: str
    transcript_version: int
    policy_ref: str
    segments: list[Segment]


def _clean(name: str) -> str:
    return " ".join(name.split())


def _assertion_id(source: Source, proposal: Proposal, subject: str, obj: str) -> str:
    raw = f"{source.recording_id}|{source.transcript_version}|{subject.casefold()}|"
    raw += f"{proposal.relation.value}|{obj.casefold()}|{proposal.segment_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _part_of(a: str, b: str) -> bool:
    """One name is the other, or a word inside it (a proverb about an elephant is not 'about'
    the elephant). Tamil words carry endings, so a stem inside a longer word counts too."""
    a, b = a.casefold(), b.casefold()
    return a in b or b in a


def _acceptable(proposal: Proposal, subject: str, obj: str, known: set[str]) -> bool:
    names_ok = 0 < len(subject) <= MAX_NAME and 0 < len(obj) <= MAX_NAME
    return (
        names_ok
        and proposal.relation in PROPOSABLE
        and proposal.segment_id in known
        and not _part_of(subject, obj)
    )


def _to_assertion(
    source: Source, proposal: Proposal, speakers: dict[str, str]
) -> GraphAssertion | None:
    subject, obj = _clean(proposal.subject), _clean(proposal.object)
    if not _acceptable(proposal, subject, obj, set(speakers)):
        return None
    return GraphAssertion(
        id=_assertion_id(source, proposal, subject, obj),
        recording_id=source.recording_id,
        subject=subject,
        relation=proposal.relation,
        object=obj,
        asserted_by=speakers[proposal.segment_id],
        review_state=ReviewState.PENDING,
        supporting_segment_id=proposal.segment_id,
        transcript_version=source.transcript_version,
        confidence=proposal.confidence,
        policy_ref=source.policy_ref,
    )


def _batches(segments: list[Segment]) -> list[list[Segment]]:
    return [segments[start : start + BATCH_SIZE] for start in range(0, len(segments), BATCH_SIZE)]


class GraphExtractor:
    """Reads a transcript in batches and returns validated, pending assertions."""

    def __init__(self, runner: Invoker) -> None:
        self._runner = runner

    def extract(self, source: Source) -> list[GraphAssertion]:
        speakers = {s.segment_id: s.speaker or UNKNOWN_SPEAKER for s in source.segments}
        found: dict[str, GraphAssertion] = {}
        for batch in _batches(source.segments):
            for assertion in self._assertions(batch, source, speakers):
                found.setdefault(assertion.id, assertion)
        return list(found.values())[:MAX_PER_RECORDING]

    def _assertions(
        self, batch: list[Segment], source: Source, speakers: dict[str, str]
    ) -> list[GraphAssertion]:
        converted = (_to_assertion(source, p, speakers) for p in self._propose(batch))
        return [a for a in converted if a is not None]

    def _propose(self, batch: list[Segment]) -> list[Proposal]:
        payload = [
            {"segment_id": s.segment_id, "speaker": s.speaker, "text": s.text} for s in batch
        ]
        result: Any = self._runner.invoke(
            {"segments_json": json.dumps(payload, ensure_ascii=False)}
        )
        if not isinstance(result, Proposals):
            raise ProviderError("unexpected extraction output", code=EXTRACTION)
        return result.assertions
