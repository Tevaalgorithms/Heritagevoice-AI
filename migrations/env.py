"""Alembic environment. Online mode only; the URL comes from settings, never from this repo."""

from alembic import context

from app.config import Settings
from app.db.engine import engine_from_settings
from app.db.tables import Base


def run_migrations_online() -> None:
    engine = engine_from_settings(Settings())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported; set HERITAGEVOICE_DATABASE_URL")
run_migrations_online()
