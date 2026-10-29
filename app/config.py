"""Environment configuration; never expose SecretStr values in responses."""

from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.security.roles import Role


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HERITAGEVOICE_", env_file=".env", extra="ignore")
    environment: str = "local"
    dev_api_token: SecretStr | None = None
    dev_role: Role = Role.MEMBER
    api_url: str = "http://127.0.0.1:8000"
    database_url: SecretStr | None = None
    audio_bucket: str | None = None
    audio_kms_key_id: str | None = None
    audio_local_dir: str | None = None
    max_audio_mb: int = Field(default=200, gt=0)
    max_audio_minutes: int = Field(default=120, gt=0)
    allowed_languages: str = "ta,en"
    asr_provider: Literal["transcribe", "fake"] = "transcribe"
    cognito_region: str | None = None
    cognito_user_pool_id: str | None = None
    cognito_app_client_id: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str = "claude-sonnet-5-5"
    llm_timeout_s: float = Field(default=30.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    # The Pinecone SDK reads these unprefixed names itself, so we accept the same ones.
    pinecone_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("PINECONE_API_KEY")
    )
    pinecone_index: str | None = Field(
        default=None, validation_alias=AliasChoices("PINECONE_INDEX")
    )


class IntegrationNotConfiguredError(RuntimeError):
    """An adapter must be implemented before the MVP is ready."""
