"""Build the worker's handler registry from settings. Missing configuration means no handler."""

import logging
from collections.abc import Callable, Mapping
from functools import partial

from pinecone import Pinecone
from sqlalchemy import Engine

from app.adapters.llm_translator import build_translator
from app.adapters.pinecone_store import PineconeEmbedder, PineconeVectorStore
from app.adapters.transcribe import AmazonTranscribe, TranscribeConfig
from app.config import Settings
from app.db.session import session_scope
from app.fakes import FakeTranscriber
from app.indexing import INDEX_KIND, UNINDEX_KIND, IndexDeps, index_recording, unindex_recording
from app.ingest import IngestDeps, ingest_handler
from app.model_registry import ModelRegistry
from app.models.evidence import Evidence
from app.models.job import Job, Outcome
from app.models.transcript import Segment
from app.ports import Transcriber, VectorStore
from app.retrieval.evidence_store import hydrate
from app.security.permissions import Principal
from app.uploads import INGEST_KIND

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


def _vector_store(settings: Settings, engine: Engine) -> VectorStore | None:
    """Pinecone when a key and index are configured; otherwise keyword search only."""
    if settings.pinecone_api_key is None or not settings.pinecone_index:
        logger.warning("Pinecone is not configured; only keyword search will be indexed")
        return None
    client = Pinecone(api_key=settings.pinecone_api_key.get_secret_value())

    def hydrate_for(ids: list[str], principal: Principal) -> list[Evidence]:
        with session_scope(engine) as session:
            return hydrate(session, ids, principal, "vector")

    embedder = PineconeEmbedder(client, settings.embedding_model)
    index = client.Index(settings.pinecone_index)
    return PineconeVectorStore(index, embedder, hydrate_for, settings.embedding_dimension)


def index_deps(settings: Settings, engine: Engine) -> IndexDeps:
    return IndexDeps(lambda: session_scope(engine), _vector_store(settings, engine))


def _ingest_handlers(settings: Settings, engine: Engine) -> dict[str, Handler]:
    transcriber = _transcriber(settings)
    if transcriber is None:
        logger.warning("No speech service configured; ingestion jobs will fail with no_handler")
        return {}
    registry = ModelRegistry(lambda: session_scope(engine), settings)
    translator = build_translator(settings, registry)
    deps = IngestDeps(lambda: session_scope(engine), transcriber, translator)
    return {INGEST_KIND: ingest_handler(deps)}


def build_handlers(settings: Settings, engine: Engine) -> Mapping[str, Handler]:
    deps = index_deps(settings, engine)
    return {
        **_ingest_handlers(settings, engine),
        INDEX_KIND: partial(index_recording, deps=deps),
        UNINDEX_KIND: partial(unindex_recording, deps=deps),
    }
