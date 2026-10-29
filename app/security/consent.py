"""Consent gate: call before any provider, index or playback step. Denial raises, never returns."""

from app.models.records import Consent, Right


class ConsentDeniedError(PermissionError):
    """The needed right is missing, was never granted, or has been revoked."""


def require_right(consent: Consent | None, right: Right) -> None:
    if consent is None or not consent.permits(right):
        raise ConsentDeniedError(f"Consent does not permit {right}")
