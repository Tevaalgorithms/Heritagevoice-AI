"""Segment translation with a LangChain chain: prompt -> chat model -> structured output.

The chain is injected, so tests use a fake and production uses the configured chat model. Output
is validated: the same segment IDs in the same order, never empty. Anything else is a provider
failure (`mt`), so the worker can retry or fall back to a transcript-only draft.
"""

import json
import logging
from collections.abc import Callable
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.runnables import Runnable
from pydantic import BaseModel, SecretStr

from app.agents.prompts.translation import TRANSLATION_PROMPT
from app.config import Settings
from app.errors import ProviderError
from app.model_registry import ModelRegistry
from app.models.llm import ModelRole, ModelSetting
from app.models.transcript import Segment
from app.ports import Translator

logger = logging.getLogger("heritagevoice.translator")
MT = "mt"
BATCH_SIZE = 20
LANGUAGE_NAMES = {"en": "English", "ta": "Tamil"}


class TranslatedSegment(BaseModel):
    segment_id: str
    text: str


class TranslationBatch(BaseModel):
    segments: list[TranslatedSegment]


class LangChainTranslator:
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
    options: dict[str, Any] = {
        "model": setting.model,
        "api_key": api_key,
        "timeout": setting.timeout_s,
        "max_retries": setting.max_retries,
        "temperature": setting.temperature,
    }
    model = ChatAnthropic(**options)
    structured = model.with_structured_output(TranslationBatch, method="json_schema")
    return TRANSLATION_PROMPT | structured


class ConfiguredTranslator:
    """Follows the registry: each call uses the model setting in force at that moment."""

    def __init__(
        self,
        registry: ModelRegistry,
        api_key: SecretStr,
        chain_factory: ChainFactory = build_chain,
    ) -> None:
        self._registry = registry
        self._api_key = api_key
        self._chain_factory = chain_factory
        self._built: dict[ModelSetting, LangChainTranslator] = {}

    def translate(self, segments: list[Segment], target_language: str) -> list[Segment]:
        return self._translator(self._registry.get(ModelRole.TRANSLATION)).translate(
            segments, target_language
        )

    def _translator(self, setting: ModelSetting) -> LangChainTranslator:
        if setting not in self._built:
            self._built[setting] = LangChainTranslator(self._chain_factory(setting, self._api_key))
        return self._built[setting]


def build_translator(settings: Settings, registry: ModelRegistry) -> Translator | None:
    """None when no model key is configured: ingestion then stops at the draft transcript."""
    if settings.llm_api_key is None:
        return None
    return ConfiguredTranslator(registry, settings.llm_api_key)
