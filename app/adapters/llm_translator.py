"""Segment translation with a LangChain chain: prompt -> chat model -> structured output.

The chain is injected, so tests use a fake and production uses the configured chat model. Output
is validated: the same segment IDs in the same order, never empty. Anything else is a provider
failure (`mt`), so the worker can retry or fall back to a transcript-only draft.
"""

import hashlib
import json
import logging
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import Runnable
from pydantic import BaseModel, SecretStr

from app.adapters.chat_models import ChatOptions, chat_model, structured
from app.agents.prompts.translation import TRANSLATION_PROMPT
from app.errors import ProviderError
from app.model_registry import ModelRegistry
from app.models.llm import ModelRole, ModelSetting
from app.models.transcript import Segment
from app.ports import Translator
from app.secrets import SecretReader

logger = logging.getLogger("heritagevoice.translator")
MT = "mt"
BATCH_SIZE = 20
LANGUAGE_NAMES = {"en": "English", "ta": "Tamil"}


class TranslatedSegment(BaseModel):
    """One translated segment, tied to its source by segment ID."""

    segment_id: str
    text: str


class TranslationBatch(BaseModel):
    """The structured answer the model must return for a batch of segments."""

    segments: list[TranslatedSegment]


class LangChainTranslator:
    """Translates segments with one LangChain chain and validates what comes back."""

    def __init__(self, chain: Runnable[dict[str, str], Any]) -> None:
        self._chain = chain

    def translate(self, segments: list[Segment], target_language: str) -> list[Segment]:
        language = LANGUAGE_NAMES.get(target_language, target_language)
        translated: list[Segment] = []
        for start in range(0, len(segments), BATCH_SIZE):
            translated.extend(self._batch(segments[start : start + BATCH_SIZE], language))
        return translated

    def _batch(self, batch: list[Segment], language: str) -> list[Segment]:
        payload = [{"segment_id": s.segment_id, "text": s.text} for s in batch]
        inputs = {
            "target_language": language,
            "segments_json": json.dumps(payload, ensure_ascii=False),
        }
        try:
            result = self._chain.invoke(inputs)
        except Exception as error:  # provider and parser errors alike; log the type only
            logger.warning("translation call failed: %s", type(error).__name__)
            raise ProviderError("translation call failed", code=MT) from error
        return _validated(batch, result)


def _same_segments(batch: list[Segment], returned: Any) -> bool:
    return isinstance(returned, list) and [r.segment_id for r in returned] == [
        s.segment_id for s in batch
    ]


def _usable(batch: list[Segment], returned: list[Any]) -> bool:
    return _same_segments(batch, returned) and all(r.text.strip() for r in returned)


def _validated(batch: list[Segment], result: Any) -> list[Segment]:
    returned: list[Any] = getattr(result, "segments", None) or []
    if not _usable(batch, returned):
        raise ProviderError("translation did not match the input segments", code=MT)
    return [s.model_copy(update={"text": r.text}) for s, r in zip(batch, returned, strict=True)]


ChainFactory = Callable[[ModelSetting, SecretStr], Runnable[dict[str, str], Any]]


def build_chain(setting: ModelSetting, api_key: SecretStr) -> Runnable[dict[str, str], Any]:
    options = ChatOptions(
        setting.provider,
        setting.model,
        setting.timeout_s,
        setting.max_retries,
        setting.temperature,
    )
    model = chat_model(options, api_key)
    return TRANSLATION_PROMPT | structured(model, TranslationBatch, setting.provider)


class ConfiguredTranslator:
    """Follows the registry: each call tries the primary model, then the fall-backs in order.

    A model is skipped when its key is missing. It is abandoned for this call when the provider
    fails (timeout, rate limit, overload, a bad key, or output that does not match). If every
    model fails the call raises a safe `mt` error, and ingestion keeps the transcript.
    """

    def __init__(
        self,
        registry: ModelRegistry,
        secrets: SecretReader,
        chain_factory: ChainFactory = build_chain,
    ) -> None:
        self._registry = registry
        self._secrets = secrets
        self._chain_factory = chain_factory
        self._built: dict[tuple[ModelSetting, str], LangChainTranslator] = {}

    def translate(self, segments: list[Segment], target_language: str) -> list[Segment]:
        last_error: ProviderError | None = None
        for position, link in enumerate(self._registry.chain(ModelRole.TRANSLATION)):
            key = self._secrets.get(link.key_name)
            if key is None:
                logger.warning("model %s skipped: its key is not configured", link.setting.model)
                continue
            try:
                result = self._translator(link.setting, key).translate(segments, target_language)
            except ProviderError as error:
                logger.warning("model %s failed (%s); trying the next", link.setting.model, error)
                last_error = error
                continue
            _note_served(link.setting.model, position)
            return result
        raise ProviderError("no model could translate", code=MT) from last_error

    def _translator(self, setting: ModelSetting, key: SecretStr) -> LangChainTranslator:
        cache_key = (setting, _fingerprint(key))
        if cache_key not in self._built:
            self._built[cache_key] = LangChainTranslator(self._chain_factory(setting, key))
        return self._built[cache_key]


def _fingerprint(key: SecretStr) -> str:
    """Tells a rotated key from the old one without keeping the key around."""
    return hashlib.sha256(key.get_secret_value().encode()).hexdigest()[:12]


def _note_served(model: str, position: int) -> None:
    if position > 0:
        logger.warning("translation served by fall-back model %s (position %d)", model, position)


def build_translator(registry: ModelRegistry, secrets: SecretReader) -> Translator:
    """Always built: keys are read per call, so adding or rotating one needs no restart."""
    return ConfiguredTranslator(registry, secrets)
