"""Run one model call for an agent, trying the job's models in order until one answers.

The three question-answering agents (supervisor, verifier, answer) each send one structured request
to a language model. This runner gives them what translation already has: a primary model plus
fall-backs chosen on the Settings page, keys read by name at run time, and a safe failure. A model
is skipped if its key is missing and abandoned for the call if the provider fails or returns
something that does not fit the expected shape. If every model fails the caller gets a
`ProviderError` carrying only the agent's name.
"""

import hashlib
import logging
from collections.abc import Callable
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from pydantic import BaseModel, SecretStr

from app.adapters.chat_models import ChatOptions, chat_model, structured
from app.budget import BudgetExceededError
from app.errors import ProviderError
from app.model_registry import ModelRegistry
from app.models.llm import ModelRole, ModelSetting
from app.secrets import SecretReader
from app.usage import UsageCallback, UsageSink

logger = logging.getLogger("heritagevoice.agents")
ChainFactory = Callable[[ModelSetting, SecretStr], Runnable[dict[str, Any], Any]]


# A ceiling on what one call may write, so a runaway answer cannot run up the bill. Generous: the
# newer models count their own reasoning inside the limit, and a cut-off answer is a failed call.
MAX_OUTPUT_TOKENS = {
    ModelRole.SUPERVISOR: 4_000,
    ModelRole.VERIFIER: 8_000,
    ModelRole.ANSWER: 16_000,
    ModelRole.GRAPH: 32_000,
    ModelRole.TRANSLATION: 32_000,
}


def counting(setting: ModelSetting, sink: UsageSink | None) -> tuple[UsageCallback, ...]:
    """The token counter for one setting's calls, or nothing when no one is counting."""
    return () if sink is None else (UsageCallback(setting.role.value, setting.model, sink),)


def structured_chain(
    prompt: ChatPromptTemplate, schema: type[BaseModel], sink: UsageSink | None = None
) -> ChainFactory:
    """A factory for `prompt | model -> schema` using the model and limits of one setting."""

    def build(setting: ModelSetting, key: SecretStr) -> Runnable[dict[str, Any], Any]:
        options = ChatOptions(
            setting.provider,
            setting.model,
            setting.timeout_s,
            setting.max_retries,
            setting.temperature,
            MAX_OUTPUT_TOKENS[setting.role],
            callbacks=counting(setting, sink),
        )
        return prompt | structured(chat_model(options, key), schema, setting.provider)

    return build


class ModelRunner:
    """Invokes an agent's chain with fall-backs. Implements the `Invoker` the agents depend on."""

    def __init__(
        self,
        registry: ModelRegistry,
        secrets: SecretReader,
        role: ModelRole,
        chain_factory: ChainFactory,
    ) -> None:
        self._registry = registry
        self._secrets = secrets
        self._role = role
        self._factory = chain_factory
        self._built: dict[tuple[ModelSetting, str], Runnable[dict[str, Any], Any]] = {}

    def invoke(self, inputs: dict[str, Any]) -> Any:
        last_error: Exception | None = None
        for link in self._registry.chain(self._role):
            key = self._secrets.get(link.key_name)
            if key is None:
                logger.warning("%s: model %s skipped, no key", self._role, link.setting.model)
                continue
            try:
                return self._chain(link.setting, key).invoke(inputs)
            except BudgetExceededError:
                raise  # the day's share is spent: no other model may be tried either
            except Exception as error:  # provider and parser errors alike; log the type only
                logger.warning(
                    "%s: model %s failed (%s)", self._role, link.setting.model, type(error).__name__
                )
                last_error = error
        raise ProviderError("no model could serve", code=self._role.value) from last_error

    def _chain(self, setting: ModelSetting, key: SecretStr) -> Runnable[dict[str, Any], Any]:
        cache_key = (setting, hashlib.sha256(key.get_secret_value().encode()).hexdigest()[:12])
        if cache_key not in self._built:
            self._built[cache_key] = self._factory(setting, key)
        return self._built[cache_key]
