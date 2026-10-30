"""Which model each job uses. Keys are never part of this: they live in AWS Parameter Store."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelRole(StrEnum):
    """A job that calls a language model. Later segments add supervisor, verifier and answer."""

    TRANSLATION = "translation"


class Provider(StrEnum):
    """The model providers the code knows how to call."""

    ANTHROPIC = "anthropic"


DEFAULT_KEY_NAME = "HERITAGEVOICE_LLM_API_KEY"
MAX_FALLBACKS = 3
# The models present when the catalogue is first created (migration 0008). After that admins
# manage the catalogue in the Settings page; this list only seeds it.
SEED_MODELS: dict[Provider, tuple[str, ...]] = {
    Provider.ANTHROPIC: (
        "claude-fable-5-1",
        "claude-opus-5-5",
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
    ),
}


class ModelStatus(StrEnum):
    """Active models can be chosen. Deprecated ones keep serving where already chosen. Disabled
    ones serve nothing, so a role using one moves on to its next fall-back."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"


class NewModel(BaseModel):
    """An admin adds a model by name. The provider is picked from a fixed list, and the key is
    referred to by its Parameter Store *name*, never by value."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    model_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,63}$")]
    provider: Provider
    key_name: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")] = DEFAULT_KEY_NAME


class CatalogEntry(BaseModel):
    """An approved model: its provider, status and key name."""

    model_config = ConfigDict(frozen=True)
    model_id: str
    provider: Provider
    key_name: str
    status: ModelStatus = ModelStatus.ACTIVE


class StatusChange(BaseModel):
    """Request body to change a catalogue model's status."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    status: ModelStatus


class ModelParams(BaseModel):
    """What an admin can set for a role: a primary model, fall-backs in order, and limits. The
    model names are checked against the catalogue when saved."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: Provider
    model: Annotated[str, Field(min_length=1, max_length=64)]
    temperature: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    timeout_s: Annotated[float, Field(ge=5.0, le=300.0)] = 30.0
    max_retries: Annotated[int, Field(ge=0, le=5)] = 2
    fallbacks: Annotated[tuple[str, ...], Field(max_length=MAX_FALLBACKS)] = ()

    @model_validator(mode="after")
    def _chain_has_no_repeats(self) -> "ModelParams":
        chain = (self.model, *self.fallbacks)
        if len(set(chain)) != len(chain):
            raise ValueError("a model can appear only once in the chain")
        return self

    def chain(self) -> tuple[str, ...]:
        return (self.model, *self.fallbacks)


class ModelSetting(BaseModel):
    """The effective setting for one role."""

    model_config = ConfigDict(frozen=True)
    role: ModelRole
    provider: Provider
    model: str
    temperature: float
    timeout_s: float
    max_retries: int
    fallbacks: tuple[str, ...] = ()


class ProbeResult(BaseModel):
    """Outcome of the Test button: a short safe code, never provider text or the key."""

    model_config = ConfigDict(frozen=True)
    ok: bool
    code: str | None = None
