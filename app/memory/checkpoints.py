"""M01: development factory; durable storage and ownership must be implemented."""

from typing import NoReturn

from langgraph.checkpoint.memory import InMemorySaver

from app.config import IntegrationNotConfiguredError


def development_checkpointer() -> InMemorySaver:
    """RAM only; lost on restart. Never select automatically for a deployed pilot."""
    return InMemorySaver()


def persistent_checkpointer() -> NoReturn:
    raise IntegrationNotConfiguredError("Persistent checkpoints and ownership are not implemented")
