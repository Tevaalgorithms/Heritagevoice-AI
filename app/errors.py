"""Errors adapters raise so graphs can turn them into explicit failed states."""


class ProviderError(RuntimeError):
    """An external provider (ASR, LLM, index) failed or timed out."""
