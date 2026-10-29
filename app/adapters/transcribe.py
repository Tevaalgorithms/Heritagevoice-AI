"""Amazon Transcribe batch speech-to-text, behind the `Transcriber` port.

The audio is already in the private bucket, so the job reads it from there. The raw service
output is parsed, then deleted: the only copy of the text we keep is the reviewed draft in the
database. Provider failures raise `ProviderError(code="asr")` so the worker can retry.
"""

import json
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.errors import ProviderError
from app.models.transcript import Segment

LANGUAGE_CODES = {"ta": "ta-IN", "en": "en-US"}
SENTENCE_END = {".", "?", "!"}
PAUSE_BREAK_S = 1.5
MAX_WORDS = 40
MIN_DURATION_S = 0.01
ASR = "asr"
CONFIG = Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 2})


@dataclass
class _Group:
    words: list[str] = field(default_factory=list)
    start: float = 0.0
    end: float = 0.0
    speaker: str | None = None


class _Builder:
    def __init__(self) -> None:
        self.segments: list[Segment] = []
        self._group = _Group()

    def word(self, text: str, start: float, end: float, speaker: str | None) -> None:
        group = self._group
        if group.words and self._should_break(start, speaker):
            self.flush()
            group = self._group
        if not group.words:
            group.start, group.speaker = start, speaker
        group.words.append(text)
        group.end = max(end, start + MIN_DURATION_S)

    def punctuation(self, mark: str) -> None:
        if self._group.words:
            self._group.words[-1] += mark
        if mark in SENTENCE_END:
            self.flush()

    def flush(self) -> None:
        group = self._group
        if group.words:
            self.segments.append(
                Segment(
                    segment_id=f"s{len(self.segments) + 1}",
                    start_s=group.start,
                    end_s=group.end,
                    text=" ".join(group.words),
                    speaker=group.speaker,
                )
            )
        self._group = _Group()

    def _should_break(self, start: float, speaker: str | None) -> bool:
        group = self._group
        return (
            start - group.end > PAUSE_BREAK_S
            or len(group.words) >= MAX_WORDS
            or speaker != group.speaker
        )


def segments_from_items(items: list[dict[str, Any]]) -> list[Segment]:
    """Group Transcribe's word items into sentence-sized, timed segments with stable IDs."""
    builder = _Builder()
    for item in items:
        content = item["alternatives"][0]["content"]
        if item["type"] == "punctuation":
            builder.punctuation(content)
        else:
            builder.word(
                content,
                float(item["start_time"]),
                float(item["end_time"]),
                item.get("speaker_label"),
            )
    builder.flush()
    return builder.segments


@dataclass(frozen=True)
class TranscribeConfig:
    bucket: str
    kms_key_id: str | None = None
    poll_seconds: float = 5.0
    timeout_seconds: float = 900.0


@dataclass
class Runtime:
    """Clients and clock, replaceable in tests."""

    transcribe: Any = field(default_factory=lambda: boto3.client("transcribe", config=CONFIG))
    s3: Any = field(default_factory=lambda: boto3.client("s3", config=CONFIG))
    sleep: Callable[[float], None] = time.sleep
    job_name: Callable[[], str] = lambda: f"hv-{uuid4().hex}"


class AmazonTranscribe:
    def __init__(self, config: TranscribeConfig, runtime: Runtime | None = None) -> None:
        self._config = config
        self._rt = runtime or Runtime()

    def transcribe(self, audio_key: str, language: str) -> list[Segment]:
        code = LANGUAGE_CODES.get(language)
        if code is None:
            raise ProviderError("language not supported by the speech service", code=ASR)
        name = self._rt.job_name()
        output_key = f"transcripts/{name}.json"
        try:
            self._start(name, audio_key, code, output_key)
            self._wait(name)
            return segments_from_items(self._read(output_key))
        except (ClientError, BotoCoreError, KeyError, ValueError) as error:
            raise ProviderError(type(error).__name__, code=ASR) from error
        finally:
            self._cleanup(name, output_key)

    def _start(self, name: str, audio_key: str, code: str, output_key: str) -> None:
        kms = self._config.kms_key_id
        extra = {"OutputEncryptionKMSKeyId": kms} if kms else {}
        self._rt.transcribe.start_transcription_job(
            TranscriptionJobName=name,
            LanguageCode=code,
            Media={"MediaFileUri": f"s3://{self._config.bucket}/{audio_key}"},
            OutputBucketName=self._config.bucket,
            OutputKey=output_key,
            **extra,
        )

    def _wait(self, name: str) -> None:
        waited = 0.0
        while waited <= self._config.timeout_seconds:
            job = self._rt.transcribe.get_transcription_job(TranscriptionJobName=name)
            status = job["TranscriptionJob"]["TranscriptionJobStatus"]
            if status == "COMPLETED":
                return
            if status == "FAILED":
                raise ProviderError("speech service reported a failure", code=ASR)
            self._rt.sleep(self._config.poll_seconds)
            waited += self._config.poll_seconds
        raise ProviderError("speech service timed out", code=ASR)

    def _read(self, output_key: str) -> list[dict[str, Any]]:
        response = self._rt.s3.get_object(Bucket=self._config.bucket, Key=output_key)
        items: list[dict[str, Any]] = json.loads(response["Body"].read())["results"]["items"]
        return items

    def _delete_job(self, name: str) -> None:
        self._rt.transcribe.delete_transcription_job(TranscriptionJobName=name)

    def _delete_output(self, output_key: str) -> None:
        self._rt.s3.delete_object(Bucket=self._config.bucket, Key=output_key)

    def _cleanup(self, name: str, output_key: str) -> None:
        """Best effort: a leftover job or object is not worth failing the upload."""
        with suppress(ClientError, BotoCoreError):
            self._delete_job(name)
        with suppress(ClientError, BotoCoreError):
            self._delete_output(output_key)
