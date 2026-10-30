"""Verify a Cognito access token. One small function per check; any failure is a TokenError.

The API accepts access tokens only. ID tokens, other issuers, other app clients, expired tokens
and tokens signed with another algorithm are all rejected.
"""

from dataclasses import dataclass
from typing import Any, Protocol

import jwt
from pydantic import BaseModel, ConfigDict

ALGORITHMS = ["RS256"]


class TokenError(Exception):
    """The token is missing, malformed, expired, or not meant for this API."""


@dataclass(frozen=True)
class CognitoConfig:
    """Which Cognito pool and app client a token must come from."""

    region: str
    user_pool_id: str
    client_id: str

    @property
    def issuer(self) -> str:
        return f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}"

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer}/.well-known/jwks.json"


class KeyResolver(Protocol):
    """Finds the public key that signed a token."""

    def signing_key(self, token: str) -> Any: ...


class JwksKeyResolver:
    """Fetches and caches Cognito's public keys."""

    def __init__(self, jwks_url: str) -> None:
        self._client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)

    def signing_key(self, token: str) -> Any:
        return self._client.get_signing_key_from_jwt(token).key


class TokenClaims(BaseModel):
    """The claims we trust from a verified access token."""

    model_config = ConfigDict(frozen=True)
    sub: str
    groups: frozenset[str]


def _decode(token: str, config: CognitoConfig, keys: KeyResolver) -> dict[str, Any]:
    return jwt.decode(
        token,
        keys.signing_key(token),
        algorithms=ALGORITHMS,
        issuer=config.issuer,
        options={"require": ["exp", "iss", "sub"], "verify_aud": False},
    )


def _check_token_use(claims: dict[str, Any]) -> None:
    if claims.get("token_use") != "access":
        raise TokenError("Only access tokens are accepted")


def _check_client(claims: dict[str, Any], config: CognitoConfig) -> None:
    if claims.get("client_id") != config.client_id:
        raise TokenError("Token was issued to a different app client")


def _to_claims(claims: dict[str, Any]) -> TokenClaims:
    return TokenClaims(sub=str(claims["sub"]), groups=frozenset(claims.get("cognito:groups", [])))


def verify_access_token(token: str, config: CognitoConfig, keys: KeyResolver) -> TokenClaims:
    try:
        claims = _decode(token, config, keys)
    except jwt.PyJWTError as error:
        raise TokenError(type(error).__name__) from error
    _check_token_use(claims)
    _check_client(claims, config)
    return _to_claims(claims)
