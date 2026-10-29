"""Which model each job uses. Keys are never part of this: they live in AWS Parameter Store."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelRole(StrEnum):
    """A job that calls a language model. Later segments add supervisor, verifier and answer."""

    TRANSLATION = "translation"


class Provider(StrEnum):
    ANTHROPIC = "anthropic"


# Admins choose from this list, never free text, so a typo or a hostile value cannot point
# prompts at an unknown model. Add a model here (and release) before it can be selected.
ALLOWED_MODELS: dict[Provider, tuple[str, ...]] = {
    Provider.ANTHROPIC: (
        "claude-fable-5-1",
        "claude-opus-5-5",
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
    ),
}


class ModelParams(BaseModel):
    """What an admin can set. Validated against the allow-list and sane ranges."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: Provider
    model: Annotated[str, Field(min_length=1, max_length=64)]
    temperature: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    timeout_s: Annotated[float, Field(ge=5.0, le=300.0)] = 30.0
    max_retries: Annotated[int, Field(ge=0, le=5)] = 2

    @model_validator(mode="after")
    def _model_is_allowed(self) -> "ModelParams":
        if self.model not in ALLOWED_MODELS[self.provider]:
            raise ValueError("model is not in the allowed list for this provider")
        return self


class ModelSetting(BaseModel):
    """The effective setting for one role."""

    model_config = ConfigDict(frozen=True)
    role: ModelRole
    provider: Provider
    model: str
    temperature: float
    timeout_s: float
    max_retries: int


class ProbeResult(BaseModel):
    """Outcome of the Test button: a short safe code, never provider text or the key."""

    model_config = ConfigDict(frozen=True)
    ok: bool
    code: str | None = None
