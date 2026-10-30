"""The Test button: one tiny request to check that a key works with a chosen model.

Costs a few tokens. Returns a short safe code only; provider messages and the key never leave.
Works for every provider: errors are recognised by name, so no provider SDK is needed here.
"""

from pydantic import SecretStr

from app.adapters.chat_models import ChatOptions, chat_model
from app.models.llm import ModelParams, ProbeResult

PROMPT = "Reply with the single word OK."
MAX_TOKENS = 16
ERROR_CODES = {
    "AuthenticationError": "bad_key",
    "PermissionDeniedError": "bad_key",
    "NotFoundError": "unknown_model",
    "RateLimitError": "rate_limited",
}


def _code_for(error: Exception) -> str:
    return ERROR_CODES.get(type(error).__name__, "provider_error")


class ProviderModelTester:
    """Sends one tiny request to check that a model and key work together."""

    def check(self, params: ModelParams, api_key: SecretStr | None) -> ProbeResult:
        if api_key is None:
            return ProbeResult(ok=False, code="no_key")
        options = ChatOptions(
            params.provider,
            params.model,
            params.timeout_s,
            0,
            params.temperature,
            MAX_TOKENS,
        )
        try:
            chat_model(options, api_key).invoke(PROMPT)
        except Exception as error:  # report only a short code, never provider text
            return ProbeResult(ok=False, code=_code_for(error))
        return ProbeResult(ok=True)
