"""Deferred extension. Mem0 is deliberately not installed or enabled."""

from typing import NoReturn

from app.config import IntegrationNotConfiguredError


def create_mem0_adapter() -> NoReturn:
    raise IntegrationNotConfiguredError("Mem0 is outside the five-day MVP scope")
