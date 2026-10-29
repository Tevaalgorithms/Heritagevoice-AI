"""Which model setting is in force for a role.

Order: the admin's saved setting, otherwise the environment defaults. Reads are cached for a short
time so a change takes effect without a redeploy and without a database hit per request. If the
database cannot be read, the last known setting (or the defaults) keeps the service running.
"""

import logging
import time
from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.repositories import ModelSettingRepository
from app.models.llm import ModelRole, ModelSetting, Provider

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


class ModelRegistry:
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

    def get(self, role: ModelRole) -> ModelSetting:
        cached = self._cache.get(role)
        if cached is not None and cached[0] > self._clock():
            return cached[1]
        setting = self._load(role, cached)
        self._cache[role] = (self._clock() + self._ttl, setting)
        return setting

    def invalidate(self) -> None:
        self._cache.clear()

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
