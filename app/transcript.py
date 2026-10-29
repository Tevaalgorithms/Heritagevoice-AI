"""Transcript checks that hold whichever speech service produced the segments."""

from collections.abc import Callable

from app.errors import ProviderError
from app.models.transcript import Segment

ASR_CODE = "asr"
END_TOLERANCE_S = 1.0
Check = Callable[[list[Segment], float | None], str | None]


def _not_empty(segments: list[Segment], duration_s: float | None) -> str | None:
    return None if segments else "empty transcript"


def _unique_ids(segments: list[Segment], duration_s: float | None) -> str | None:
    return None if len({s.segment_id for s in segments}) == len(segments) else "duplicate IDs"


def _ordered(segments: list[Segment], duration_s: float | None) -> str | None:
    pairs = zip(segments, segments[1:], strict=False)
    return None if all(a.end_s <= b.start_s for a, b in pairs) else "overlapping segments"


def _inside_audio(segments: list[Segment], duration_s: float | None) -> str | None:
    if duration_s is None or not segments:
        return None
    return None if segments[-1].end_s <= duration_s + END_TOLERANCE_S else "beyond the audio"


CHECKS: tuple[Check, ...] = (_not_empty, _unique_ids, _ordered, _inside_audio)


def validate_segments(segments: list[Segment], duration_s: float | None) -> list[Segment]:
    """Segments must be unique, ordered, non-overlapping and inside the audio."""
    for check in CHECKS:
        problem = check(segments, duration_s)
        if problem is not None:
            raise ProviderError(problem, code=ASR_CODE)
    return segments
