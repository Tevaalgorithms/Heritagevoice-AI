"""Environment configuration; never expose SecretStr values in responses."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HERITAGEVOICE_", env_file=".env", extra="ignore")
    dev_api_token: SecretStr | None = None
    api_url: str = "http://127.0.0.1:8000"


class IntegrationNotConfigured(RuntimeError):
    """An adapter must be implemented before the MVP is ready."""
