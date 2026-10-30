"""Secret values by *name*, read at run time from AWS Parameter Store (SecureString).

The database stores only names. A value is fetched when needed and kept in memory for a few
minutes, so rotating a key in Parameter Store takes effect without a restart or a deploy. If the
store cannot be reached, or no store is configured (local development), the environment variable of
the same name is used. Values are never logged, returned by the API or stored in the database.
"""

import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import SecretStr

from app.config import Settings

logger = logging.getLogger("heritagevoice.secrets")
FOUND_TTL_S = 300.0
MISSING_TTL_S = 30.0


class SecretReader(Protocol):
    def get(self, name: str) -> SecretStr | None: ...

    def is_configured(self, name: str) -> bool: ...


@dataclass
class SecretsConfig:
    """Where values come from. The client and clock can be replaced in tests."""

    path: str | None = None
    region: str | None = None
    client: Any = None
    environ: Mapping[str, str] = field(default_factory=lambda: os.environ)
    clock: Callable[[], float] = time.monotonic


class ParameterStoreSecrets:
    def __init__(self, config: SecretsConfig) -> None:
        self._config = config
        self._path = config.path.rstrip("/") if config.path else None
        self._cache: dict[str, tuple[float, SecretStr | None]] = {}
        self._lock = threading.Lock()

    def get(self, name: str) -> SecretStr | None:
        with self._lock:
            cached = self._cache.get(name)
            if cached is not None and cached[0] > self._config.clock():
                return cached[1]
        value = self._from_store(name) or self._from_environment(name)
        ttl = FOUND_TTL_S if value is not None else MISSING_TTL_S
        with self._lock:
            self._cache[name] = (self._config.clock() + ttl, value)
        return value

    def is_configured(self, name: str) -> bool:
        return self.get(name) is not None

    def _from_environment(self, name: str) -> SecretStr | None:
        return _secret(self._config.environ.get(name))

    def _from_store(self, name: str) -> SecretStr | None:
        if self._path is None:
            return None
        return _secret(self._read(f"{self._path}/{name}"))

    def _read(self, parameter: str) -> str | None:
        try:
            response = self._ssm().get_parameter(Name=parameter, WithDecryption=True)
            return str(response["Parameter"]["Value"])
        except (ClientError, BotoCoreError) as error:
            if _code(error) != "ParameterNotFound":
                logger.warning("parameter store read failed: %s", type(error).__name__)
            return None

    def _ssm(self) -> Any:
        if self._config.client is None:
            self._config.client = boto3.client("ssm", region_name=self._config.region)
        return self._config.client


def _secret(value: str | None) -> SecretStr | None:
    return SecretStr(value) if value else None


def _code(error: Exception) -> str:
    response = getattr(error, "response", None) or {}
    return str(response.get("Error", {}).get("Code", ""))


def secrets_for(settings: Settings) -> ParameterStoreSecrets:
    return ParameterStoreSecrets(SecretsConfig(path=settings.ssm_path, region=settings.aws_region))
