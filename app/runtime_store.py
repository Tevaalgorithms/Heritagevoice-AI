"""A store built from settings saved in the admin portal.

The settings are read on every use. Until they exist there is no store; once they do it is built,
and built again whenever they change, so saving a key needs no redeploy. A failed build is logged
(never with provider text) and tried again on the next use, so a wrong address cannot break the
rest of the app.
"""

import logging
from collections.abc import Callable

logger = logging.getLogger("heritagevoice.runtime")


class RuntimeStore[Config, Store]:
    """Holds the store built from the current settings. `Config` must compare by value."""

    def __init__(
        self, load: Callable[[], Config | None], build: Callable[[Config], Store], label: str
    ) -> None:
        self._load = load
        self._build = build
        self._label = label
        self._built: tuple[Config, Store] | None = None

    def get(self) -> Store | None:
        config = self._load()
        if config is None:
            return None
        if self._built is None or self._built[0] != config:
            self._built = self._rebuilt(config)
        return None if self._built is None else self._built[1]

    def _rebuilt(self, config: Config) -> tuple[Config, Store] | None:
        store = self._try_build(config)
        return None if store is None else (config, store)

    def _try_build(self, config: Config) -> Store | None:
        try:
            return self._build(config)
        except Exception as error:  # a bad key or address: the rest of the app keeps working
            logger.warning("%s could not be set up: %s", self._label, type(error).__name__)
            return None
