"""Shared builders for tests: audio bytes, principals, and a seeded database."""

import io
import wave

from app.models.records import Consent, Right
from app.security.permissions import Principal, community_label
from app.security.roles import Role


def wav_bytes(seconds=1.0, rate=1000):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\x00\x00" * int(rate * seconds))
    return buffer.getvalue()


def person(role=Role.MEMBER, user_id="u1", communities=("c1",)):
    return Principal(
        user_id=user_id,
        groups=frozenset({"public"} | {community_label(c) for c in communities}),
        policy_version="v1",
        role=role,
        communities=frozenset(communities),
    )


def consent(consent_id="consent-1", community="c1", rights=tuple(Right), revoked=False):
    return Consent(
        id=consent_id,
        community_id=community,
        rights=frozenset(rights),
        policy_version="v1",
        revoked=revoked,
    )
