"""Database engine construction. The URL (with its password) only ever comes from settings."""

from sqlalchemy import Engine, create_engine

from app.config import IntegrationNotConfiguredError, Settings


def make_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True)


def engine_from_settings(settings: Settings) -> Engine:
    if settings.database_url is None:
        raise IntegrationNotConfiguredError("HERITAGEVOICE_DATABASE_URL is not set")
    return make_engine(settings.database_url.get_secret_value())
