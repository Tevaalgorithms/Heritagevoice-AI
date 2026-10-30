"""Group timed segments into search chunks that keep exact audio references.

A chunk is a run of consecutive segments by one speaker, about 100-250 tokens long. A segment is
never split, so every chunk resolves to whole segment IDs and one time range in the audio.
"""

from dataclasses import dataclass

from app.models.transcript import Segment
from app.retrieval.tokenize import tokens

MIN_TOKENS = 100
MAX_TOKENS = 250


@dataclass(frozen=True)
class Chunk:
    """A searchable piece of a transcript, keeping its segments and timing."""

    index: int
    text: str
    start_s: float
    end_s: float
    segment_ids: tuple[str, ...]
    speaker: str | None


def _size(segment: Segment) -> int:
    return len(tokens(segment.text))


def _starts_new_chunk(current: list[Segment], size: int, segment: Segment, max_tokens: int) -> bool:
    if not current:
        return False
    return current[-1].speaker != segment.speaker or size + _size(segment) > max_tokens


def _build(index: int, segments: list[Segment]) -> Chunk:
    return Chunk(
        index=index,
        text=" ".join(s.text.strip() for s in segments),
        start_s=segments[0].start_s,
        end_s=segments[-1].end_s,
        segment_ids=tuple(s.segment_id for s in segments),
        speaker=segments[0].speaker,
    )


def chunk_segments(segments: list[Segment], max_tokens: int = MAX_TOKENS) -> list[Chunk]:
    """Speaker turns, capped at `max_tokens`; short neighbours by the same speaker are merged."""
    chunks: list[Chunk] = []
    current: list[Segment] = []
    size = 0
    for segment in segments:
        if _starts_new_chunk(current, size, segment, max_tokens):
            chunks.append(_build(len(chunks), current))
            current, size = [], 0
        current.append(segment)
        size += _size(segment)
    if current:
        chunks.append(_build(len(chunks), current))
    return chunks
