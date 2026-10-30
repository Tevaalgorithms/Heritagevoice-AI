"""Validate an uploaded recording before it is stored or queued.

The type comes from the file's own bytes, never from its name or the client's Content-Type.
Every failure carries a short, safe code; nothing about the file content is echoed back.
"""

from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO

import mutagen

UNSUPPORTED_TYPE, TOO_LARGE, EMPTY = "unsupported_type", "too_large", "empty"
TOO_LONG, BAD_LANGUAGE, UNREADABLE = "too_long", "bad_language", "unreadable"
STATUS = {
    UNSUPPORTED_TYPE: 415,
    TOO_LARGE: 413,
    EMPTY: 422,
    TOO_LONG: 422,
    BAD_LANGUAGE: 422,
    UNREADABLE: 422,
}


class UploadError(Exception):
    """An upload was refused; carries a safe code and the HTTP status to answer with."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = STATUS[code]


@dataclass(frozen=True)
class AudioRules:
    """The limits an upload must meet: size, length and accepted languages."""

    max_bytes: int
    max_seconds: float
    languages: frozenset[str]


@dataclass(frozen=True)
class AudioInfo:
    """What was learned about an accepted audio file."""

    content_type: str
    size_bytes: int
    duration_s: float


def _is_wav(head: bytes) -> bool:
    return head[:4] == b"RIFF" and head[8:12] == b"WAVE"


MP3_SYNC = (0xFF, 0xE0)  # an MPEG frame starts with 11 set bits


def _is_mp3(head: bytes) -> bool:
    first, mask = MP3_SYNC
    framed = len(head) > 1 and head[0] == first and head[1] & mask == mask
    return head[:3] == b"ID3" or framed


def _is_mp4(head: bytes) -> bool:
    return head[4:8] == b"ftyp"


MAGIC: tuple[tuple[str, Callable[[bytes], bool]], ...] = (
    ("audio/wav", _is_wav),
    ("audio/mpeg", _is_mp3),
    ("audio/flac", lambda head: head[:4] == b"fLaC"),
    ("audio/ogg", lambda head: head[:4] == b"OggS"),
    ("audio/mp4", _is_mp4),
)


def sniff_type(head: bytes) -> str | None:
    return next((name for name, matches in MAGIC if matches(head)), None)


def check_language(language: str, rules: AudioRules) -> None:
    if language not in rules.languages:
        raise UploadError(BAD_LANGUAGE)


def check_size(size: int, rules: AudioRules) -> None:
    if size == 0:
        raise UploadError(EMPTY)
    if size > rules.max_bytes:
        raise UploadError(TOO_LARGE)


def measure_duration(data: bytes) -> float:
    try:
        parsed = mutagen.File(BytesIO(data))
    except mutagen.MutagenError as error:
        raise UploadError(UNREADABLE) from error
    if parsed is None or parsed.info is None or not parsed.info.length:
        raise UploadError(UNREADABLE)
    return float(parsed.info.length)


def check_duration(seconds: float, rules: AudioRules) -> None:
    if seconds > rules.max_seconds:
        raise UploadError(TOO_LONG)


def validate_audio(data: bytes, rules: AudioRules) -> AudioInfo:
    check_size(len(data), rules)
    content_type = sniff_type(data[:16])
    if content_type is None:
        raise UploadError(UNSUPPORTED_TYPE)
    seconds = measure_duration(data)
    check_duration(seconds, rules)
    return AudioInfo(content_type, len(data), seconds)
