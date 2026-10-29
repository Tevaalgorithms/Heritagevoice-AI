"""Pure display helpers for the upload and transcript views."""

from frontend.api_client import SegmentView

STAGE_PROGRESS = {None: 0.1, "transcribe": 0.7, "translate": 0.9}
STATUS_LABELS = {
    "queued": "Waiting to start",
    "processing": "Transcribing",
    "review": "Draft ready for review",
    "failed": "Processing failed",
}
FAILURE_MESSAGES = {
    "asr": "The speech service could not transcribe this recording. Try again later.",
    "mt": "The translation step failed. Try again later.",
    "consent": "Processing was stopped because consent does not cover this recording.",
}
SECONDS_PER_MINUTE = 60


def format_time(seconds: float) -> str:
    minutes, rest = divmod(seconds, SECONDS_PER_MINUTE)
    return f"{int(minutes):02d}:{rest:04.1f}"


def segment_rows(segments: list[SegmentView]) -> list[dict[str, str]]:
    return [
        {
            "From": format_time(s.start_s),
            "To": format_time(s.end_s),
            "Speaker": s.speaker or "",
            "Text": s.text,
        }
        for s in segments
    ]


def progress_for(status: str, stage: str | None) -> tuple[float, str]:
    if status in {"review", "published"}:
        return 1.0, STATUS_LABELS["review"]
    return STAGE_PROGRESS.get(stage, 0.1), STATUS_LABELS.get(status, status)


def failure_message(code: str | None) -> str:
    return FAILURE_MESSAGES.get(code or "", "Processing failed. Please contact an administrator.")


def editor_rows(segments: list[SegmentView]) -> list[dict[str, str]]:
    """Rows for the edit table; only the text column is editable in the UI."""
    return [{"id": s.segment_id, "time": _span(s), "text": s.text} for s in segments]


def _span(segment: SegmentView) -> str:
    return f"{format_time(segment.start_s)}-{format_time(segment.end_s)}"


def _new_text(row: dict[str, str], before: dict[str, str]) -> str | None:
    text = row["text"].strip()
    return text if text and row["id"] in before and text != before[row["id"]] else None


def changed_edits(original: list[SegmentView], edited: list[dict[str, str]]) -> dict[str, str]:
    """Only the segments whose text actually changed, keyed by segment ID."""
    before = {s.segment_id: s.text for s in original}
    pairs = ((row["id"], _new_text(row, before)) for row in edited)
    return {sid: text for sid, text in pairs if text is not None}
