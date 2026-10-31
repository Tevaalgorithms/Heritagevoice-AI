"""Build the worker's handler registry from settings. Missing configuration means no handler."""

import logging
from collections.abc import Callable, Mapping
from functools import partial

from sqlalchemy import Engine

from app.adapters.llm_translator import build_translator
from app.adapters.transcribe import AmazonTranscribe, TranscribeConfig
from app.config import Settings
from app.db.session import session_scope
from app.fakes import FakeTranscriber
from app.graph_setup import RuntimeGraphProjection
from app.indexing import INDEX_KIND, UNINDEX_KIND, IndexDeps, index_recording, unindex_recording
from app.ingest import IngestDeps, ingest_handler
from app.model_registry import ModelRegistry
from app.models.job import Job, Outcome
from app.models.transcript import Segment
from app.ports import Transcriber
from app.secrets import secrets_for
from app.uploads import INGEST_KIND
from app.vector_setup import vector_store_for

logger = logging.getLogger("heritagevoice.worker")
Handler = Callable[[Job], Outcome]
LOCAL = "local"
DEV_SEGMENTS = [
    Segment(segment_id="s1", start_s=0.0, end_s=0.4, text="Development transcript, first part."),
    Segment(segment_id="s2", start_s=0.4, end_s=0.8, text="Development transcript, second part."),
]


def _transcriber(settings: Settings) -> Transcriber | None:
    if settings.asr_provider == "fake" and settings.environment == LOCAL:
        return FakeTranscriber(DEV_SEGMENTS)
    if settings.audio_bucket:
        config = TranscribeConfig(
            settings.audio_bucket, settings.audio_kms_key_id, settings.aws_region
        )
        return AmazonTranscribe(config)
    return None


def index_deps(settings: Settings, engine: Engine) -> IndexDeps:
    return IndexDeps(
        lambda: session_scope(engine),
        vector_store_for(settings, engine),
        RuntimeGraphProjection(secrets_for(settings)),
    )


def _ingest_handlers(settings: Settings, engine: Engine) -> dict[str, Handler]:
    transcriber = _transcriber(settings)
    if transcriber is None:
        logger.warning("No speech service configured; ingestion jobs will fail with no_handler")
        return {}
    registry = ModelRegistry(lambda: session_scope(engine), settings)
    translator = build_translator(registry, secrets_for(settings))
    deps = IngestDeps(lambda: session_scope(engine), transcriber, translator)
    return {INGEST_KIND: ingest_handler(deps)}


def build_handlers(settings: Settings, engine: Engine) -> Mapping[str, Handler]:
    deps = index_deps(settings, engine)
    return {
        **_ingest_handlers(settings, engine),
        INDEX_KIND: partial(index_recording, deps=deps),
        UNINDEX_KIND: partial(unindex_recording, deps=deps),
    }
