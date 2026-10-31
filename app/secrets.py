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
from functools import lru_cache
from typing import Any, Protocol

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import SecretStr

from app.config import Settings

logger = logging.getLogger("heritagevoice.secrets")
FOUND_TTL_S = 300.0
MISSING_TTL_S = 30.0


class SecretReader(Protocol):
    """Reads a secret by name; the value never leaves memory."""

    def get(self, name: str) -> SecretStr | None: ...

    def is_configured(self, name: str) -> bool: ...


def secret_text(reader: SecretReader, name: str) -> str | None:
    """The saved value as plain text, or None if it is not set."""
    value = reader.get(name)
    return value.get_secret_value() if value else None


@dataclass
class SecretsConfig:
    """Where values come from. The client and clock can be replaced in tests."""

    path: str | None = None
    region: str | None = None
    client: Any = None
    environ: Mapping[str, str] = field(default_factory=lambda: os.environ)
    clock: Callable[[], float] = time.monotonic


class ParameterStoreSecrets:
    """Reads secrets from AWS Parameter Store, cached briefly, with the environment as fallback."""

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

    def forget(self, name: str) -> None:
        """Drop the cached value, so the next read sees what was just written."""
        with self._lock:
            self._cache.pop(name, None)

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


WRITE_DENIED = "write_denied"
WRITE_FAILED = "write_failed"
NOT_CONFIGURED = "not_configured"


class SecretWriteError(Exception):
    """A value could not be saved. `code` is a short, safe label; the message never leaves."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SecretWriter(Protocol):
    """Saves a value by name. The value is never returned or logged."""

    def put(self, name: str, value: str, secret: bool) -> None: ...


class ParameterStoreWriter:
    """Saves a value under the site's path. Secrets are encrypted with the site's key."""

    def __init__(self, path: str | None, region: str | None = None, client: Any = None) -> None:
        self._path = path.rstrip("/") if path else None
        self._region = region
        self._client = client

    def put(self, name: str, value: str, secret: bool) -> None:
        if self._path is None:
            raise SecretWriteError(NOT_CONFIGURED)
        try:
            self._ssm().put_parameter(**self._arguments(self._path, name, value, secret))
        except (ClientError, BotoCoreError) as error:
            logger.warning("parameter store write failed: %s", type(error).__name__)
            denied = _code(error) == "AccessDeniedException"
            raise SecretWriteError(WRITE_DENIED if denied else WRITE_FAILED) from error

    @staticmethod
    def _arguments(path: str, name: str, value: str, secret: bool) -> dict[str, Any]:
        """The request: secrets are encrypted with the site's key, plain settings are not."""
        arguments: dict[str, Any] = {
            "Name": f"{path}/{name}",
            "Value": value,
            "Type": "SecureString" if secret else "String",
            "Overwrite": True,
        }
        if secret:
            arguments["KeyId"] = f"alias/heritagevoice-{path.rsplit('/', 1)[-1]}"
        return arguments

    def _ssm(self) -> Any:
        if self._client is None:
            self._client = boto3.client("ssm", region_name=self._region)
        return self._client


@lru_cache(maxsize=4)
def _shared_reader(path: str | None, region: str | None) -> ParameterStoreSecrets:
    return ParameterStoreSecrets(SecretsConfig(path=path, region=region))


def secrets_for(settings: Settings) -> ParameterStoreSecrets:
    """One reader per process, so its short cache is shared by every request."""
    return _shared_reader(settings.ssm_path, settings.aws_region)


def writer_for(settings: Settings) -> ParameterStoreWriter:
    return ParameterStoreWriter(settings.ssm_path, settings.aws_region)
