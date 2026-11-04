"""Build what a spoken correction needs from settings. Missing configuration means no voice."""

from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy.orm import Session

from app.adapters.llm_runner import ModelRunner, structured_chain
from app.agents.correction_interpreter import CorrectionInterpreter, Interpretation
from app.agents.prompts.correction import CORRECTION_PROMPT
from app.agents.translator import build_translator
from app.audio import AudioRules
from app.config import Settings
from app.model_registry import ModelRegistry
from app.models.llm import ModelRole
from app.ports import AudioStore
from app.secrets import secrets_for
from app.usage import UsageLog
from app.voice_correction import VoiceDeps
from app.worker_setup import transcriber_for

SessionFactory = Callable[[], AbstractContextManager[Session]]


def build_voice_deps(
    settings: Settings, sessions: SessionFactory, store: AudioStore, rules: AudioRules
) -> VoiceDeps | None:
    """None when speech-to-text is not configured on this server."""
    transcriber = transcriber_for(settings)
    if transcriber is None:
        return None
    registry, keys, usage = (
        ModelRegistry(sessions, settings),
        secrets_for(settings),
        UsageLog(sessions),
    )
    chain = structured_chain(CORRECTION_PROMPT, Interpretation, usage)
    interpreter = CorrectionInterpreter(ModelRunner(registry, keys, ModelRole.GRAPH, chain))
    return VoiceDeps(
        store, transcriber, build_translator(registry, keys, usage), interpreter, rules
    )
