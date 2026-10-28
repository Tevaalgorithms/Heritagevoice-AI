"""Deferred extension. Mem0 is deliberately not installed or enabled."""

from app.config import IntegrationNotConfigured


def create_mem0_adapter():
    raise IntegrationNotConfigured("Mem0 is outside the five-day MVP scope")
