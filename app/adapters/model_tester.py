"""The Test button: one tiny request to check that the stored key works with a chosen model.

Costs a few tokens. Returns a short safe code only; provider messages and the key never leave.
"""

from typing import Any

import anthropic
from langchain_anthropic import ChatAnthropic
from pydantic import SecretStr

from app.models.llm import ModelParams, ProbeResult

PROMPT = "Reply with the single word OK."
MAX_TOKENS = 8
ERROR_CODES: tuple[tuple[type[Exception], str], ...] = (
    (anthropic.AuthenticationError, "bad_key"),
    (anthropic.PermissionDeniedError, "bad_key"),
    (anthropic.NotFoundError, "unknown_model"),
    (anthropic.RateLimitError, "rate_limited"),
)


def _code_for(error: Exception) -> str:
    return next((code for kind, code in ERROR_CODES if isinstance(error, kind)), "provider_error")


class AnthropicModelTester:
    def check(self, params: ModelParams, api_key: SecretStr | None) -> ProbeResult:
        if api_key is None:
            return ProbeResult(ok=False, code="no_key")
        options: dict[str, Any] = {
            "model": params.model,
            "api_key": api_key,
            "timeout": params.timeout_s,
            "max_retries": 0,
            "temperature": params.temperature,
            "max_tokens": MAX_TOKENS,
        }
        try:
            ChatAnthropic(**options).invoke(PROMPT)
        except Exception as error:  # report only a short code, never provider text
            return ProbeResult(ok=False, code=_code_for(error))
        return ProbeResult(ok=True)
