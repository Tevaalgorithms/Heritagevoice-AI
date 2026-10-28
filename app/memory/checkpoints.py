"""M01: development factory; durable storage and ownership must be implemented."""

from langgraph.checkpoint.memory import InMemorySaver

from app.config import IntegrationNotConfigured


def development_checkpointer() -> InMemorySaver:
    """RAM only; lost on restart. Never select automatically for a deployed pilot."""
    return InMemorySaver()


def persistent_checkpointer():
    raise IntegrationNotConfigured("Persistent checkpoints and ownership are not implemented")
