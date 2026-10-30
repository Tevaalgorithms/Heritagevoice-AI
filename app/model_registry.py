"""Which model setting is in force for a role.

Order: the admin's saved setting, otherwise the environment defaults. Reads are cached for a short
time so a change takes effect without a redeploy and without a database hit per request. If the
database cannot be read, the last known setting (or the defaults) keeps the service running.
"""

import logging
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.repositories import ModelCatalogRepository, ModelSettingRepository
from app.models.llm import (
    DEFAULT_KEY_NAME,
    CatalogEntry,
    ModelRole,
    ModelSetting,
    ModelStatus,
    Provider,
)

logger = logging.getLogger("heritagevoice.models")
SessionFactory = Callable[[], AbstractContextManager[Session]]
DEFAULT_TTL_S = 60.0


def default_setting(role: ModelRole, settings: Settings) -> ModelSetting:
    """From the environment. Trusted configuration, so it is not limited to the admin allow-list."""
    return ModelSetting(
        role=role,
        provider=Provider.ANTHROPIC,
        model=settings.llm_model,
        temperature=0.0,
        timeout_s=settings.llm_timeout_s,
        max_retries=settings.llm_max_retries,
    )


@dataclass(frozen=True)
class ChainLink:
    """One model to try for a role: its full setting, and the *name* of the key that serves it."""

    setting: ModelSetting
    key_name: str


class ModelRegistry:
    """Decides which models serve a job, reading settings and the catalogue with a short cache."""

    def __init__(
        self,
        sessions: SessionFactory,
        defaults: Settings,
        ttl_s: float = DEFAULT_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sessions = sessions
        self._defaults = defaults
        self._ttl = ttl_s
        self._clock = clock
        self._cache: dict[ModelRole, tuple[float, ModelSetting]] = {}
        self._catalog_cache: tuple[float, dict[str, CatalogEntry]] | None = None

    def get(self, role: ModelRole) -> ModelSetting:
        cached = self._cache.get(role)
        if cached is not None and cached[0] > self._clock():
            return cached[1]
        setting = self._load(role, cached)
        self._cache[role] = (self._clock() + self._ttl, setting)
        return setting

    def chain(self, role: ModelRole) -> list[ChainLink]:
        """The models to try, in order: the primary, then each fall-back. Disabled models and
        fall-backs missing from the catalogue are skipped; deprecated models still serve."""
        setting = self.get(role)
        catalog = self._catalog()
        links = [self._link(setting, model_id, catalog) for model_id in _chain_ids(setting)]
        return [link for link in links if link is not None]

    def invalidate(self) -> None:
        self._cache.clear()
        self._catalog_cache = None

    def _link(
        self, setting: ModelSetting, model_id: str, catalog: dict[str, CatalogEntry]
    ) -> ChainLink | None:
        entry = catalog.get(model_id)
        if entry is None:
            # The primary may come from trusted environment configuration; it uses the default key.
            return (
                _link_for(setting, model_id, setting.provider, DEFAULT_KEY_NAME)
                if (model_id == setting.model)
                else None
            )
        if entry.status is ModelStatus.DISABLED:
            return None
        return _link_for(setting, model_id, entry.provider, entry.key_name)

    def _catalog(self) -> dict[str, CatalogEntry]:
        cached = self._catalog_cache
        if cached is not None and cached[0] > self._clock():
            return cached[1]
        entries = self._load_catalog(cached)
        self._catalog_cache = (self._clock() + self._ttl, entries)
        return entries

    def _load_catalog(
        self, stale: tuple[float, dict[str, CatalogEntry]] | None
    ) -> dict[str, CatalogEntry]:
        try:
            with self._sessions() as session:
                return {e.model_id: e for e in ModelCatalogRepository(session).list_all()}
        except SQLAlchemyError as error:
            logger.warning(
                "model catalogue unreadable (%s); using the last known", type(error).__name__
            )
            return stale[1] if stale is not None else {}

    def _load(self, role: ModelRole, stale: tuple[float, ModelSetting] | None) -> ModelSetting:
        try:
            with self._sessions() as session:
                saved = ModelSettingRepository(session).get(role)
        except SQLAlchemyError as error:
            logger.warning(
                "model settings unreadable (%s); using the last known value", type(error).__name__
            )
            return stale[1] if stale is not None else default_setting(role, self._defaults)
        return saved if saved is not None else default_setting(role, self._defaults)


def _chain_ids(setting: ModelSetting) -> tuple[str, ...]:
    return (setting.model, *setting.fallbacks)


def _link_for(setting: ModelSetting, model_id: str, provider: Provider, key_name: str) -> ChainLink:
    own = setting.model_copy(update={"model": model_id, "provider": provider, "fallbacks": ()})
    return ChainLink(own, key_name)
