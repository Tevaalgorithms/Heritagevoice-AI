"""Choose the few passages that go to the answer step: best first, within a size budget.

Quality over quantity: 5 to 8 passages, no more than a couple from one recording so the answer is
not built from a single voice, and a token budget so the prompt stays small. The size is an
estimate (UTF-8 bytes divided by four), which over-counts Tamil and other non-Latin scripts and so
errs on the safe side.
"""

from dataclasses import dataclass

from app.retrieval.fusion import FusedHit

MAX_PASSAGES = 8
PER_RECORDING = 2
TOKEN_BUDGET = 3000
BYTES_PER_TOKEN = 4


@dataclass(frozen=True)
class SelectionLimits:
    """How many passages, how many per recording, and how large in total."""

    max_passages: int = MAX_PASSAGES
    per_recording: int = PER_RECORDING
    token_budget: int = TOKEN_BUDGET


DEFAULT_LIMITS = SelectionLimits()


def estimate_tokens(text: str) -> int:
    return max(1, -(-len(text.encode("utf-8")) // BYTES_PER_TOKEN))


def _fits(
    hit: FusedHit, spent: int, per_recording: dict[str, int], limits: SelectionLimits
) -> bool:
    recording = hit.evidence.document_id
    within_recording = per_recording.get(recording, 0) < limits.per_recording
    within_budget = spent + estimate_tokens(hit.evidence.passage) <= limits.token_budget
    return within_recording and within_budget


def select_passages(
    hits: list[FusedHit], limits: SelectionLimits = DEFAULT_LIMITS
) -> list[FusedHit]:
    """The best passages that fit the limits. The top hit is always kept, even if it is long."""
    chosen: list[FusedHit] = []
    per_recording: dict[str, int] = {}
    spent = 0
    for hit in hits:
        if len(chosen) >= limits.max_passages:
            break
        if chosen and not _fits(hit, spent, per_recording, limits):
            continue
        chosen.append(hit)
        spent += estimate_tokens(hit.evidence.passage)
        recording = hit.evidence.document_id
        per_recording[recording] = per_recording.get(recording, 0) + 1
    return chosen
