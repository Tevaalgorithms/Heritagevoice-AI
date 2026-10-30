"""Readiness: each dependency is one small check. Unconfigured optional services are skipped."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import boto3
from botocore.config import Config
from sqlalchemy import text

from app.config import Settings
from app.db.engine import engine_from_settings

logger = logging.getLogger("heritagevoice.ready")
CheckStatus = Literal["ok", "failed", "not_configured", "skipped"]
S3_CONFIG = Config(connect_timeout=3, read_timeout=3, retries={"max_attempts": 1})


@dataclass(frozen=True)
class Check:
    """One dependency the service reports on: whether it is required, configured and healthy."""

    name: str
    required: bool
    configured: Callable[[Settings], bool]
    probe: Callable[[Settings], None]


def probe_postgres(settings: Settings) -> None:
    with engine_from_settings(settings).connect() as connection:
        connection.execute(text("select 1"))


def probe_bucket(settings: Settings) -> None:
    boto3.client("s3", config=S3_CONFIG).head_bucket(Bucket=settings.audio_bucket)


CHECKS = (
    Check("postgres", True, lambda s: s.database_url is not None, probe_postgres),
    Check("audio_bucket", False, lambda s: s.audio_bucket is not None, probe_bucket),
)


def run_check(check: Check, settings: Settings) -> CheckStatus:
    if not check.configured(settings):
        return "not_configured" if check.required else "skipped"
    try:
        check.probe(settings)
    except Exception as error:  # report only the check name and error type, never details
        logger.warning("readiness check %s failed: %s", check.name, type(error).__name__)
        return "failed"
    return "ok"


def passes(check: Check, status: CheckStatus) -> bool:
    return status == "ok" or (not check.required and status == "skipped")


def run_checks(settings: Settings) -> tuple[bool, dict[str, CheckStatus]]:
    statuses = {check.name: run_check(check, settings) for check in CHECKS}
    return all(passes(c, statuses[c.name]) for c in CHECKS), statuses
