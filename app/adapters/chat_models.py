"""Chat models for each provider, built in one place.

Provider addresses are fixed here, never read from settings or the database, so an admin cannot
point prompts at another server. Anthropic and OpenAI are supported; adding a provider means one
builder below and one value in `Provider`. Temperature is sent to Anthropic but not to OpenAI, whose
newer models reject anything but their default.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr

from app.models.llm import Provider

OPENAI_BASE_URL = "https://api.openai.com/v1"


@dataclass(frozen=True)
class ChatOptions:
    """What to ask a provider for: which model, how long to wait, and how creative."""

    provider: Provider
    model: str
    timeout_s: float
    max_retries: int
    temperature: float
    max_tokens: int | None = None


def _anthropic(options: ChatOptions, key: SecretStr) -> BaseChatModel:
    settings: dict[str, Any] = {
        "model": options.model,
        "api_key": key,
        "timeout": options.timeout_s,
        "max_retries": options.max_retries,
        "temperature": options.temperature,
    }
    if options.max_tokens is not None:
        settings["max_tokens"] = options.max_tokens
    return ChatAnthropic(**settings)


def _openai(options: ChatOptions, key: SecretStr) -> BaseChatModel:
    settings: dict[str, Any] = {
        "model": options.model,
        "api_key": key,
        "base_url": OPENAI_BASE_URL,
        "timeout": options.timeout_s,
        "max_retries": options.max_retries,
    }
    if options.max_tokens is not None:
        settings["max_completion_tokens"] = options.max_tokens
    return ChatOpenAI(**settings)


BUILDERS: dict[Provider, Callable[[ChatOptions, SecretStr], BaseChatModel]] = {
    Provider.ANTHROPIC: _anthropic,
    Provider.OPENAI: _openai,
}
STRUCTURED_METHOD = {Provider.ANTHROPIC: "json_schema", Provider.OPENAI: "function_calling"}


def chat_model(options: ChatOptions, key: SecretStr) -> BaseChatModel:
    return BUILDERS[options.provider](options, key)


def structured(
    model: BaseChatModel, schema: type[BaseModel], provider: Provider
) -> Runnable[Any, Any]:
    """The model constrained to answer in the shape of `schema`, as its provider supports."""
    return model.with_structured_output(schema, method=STRUCTURED_METHOD[provider])
