"""FastAPI dependencies that turn a bearer token into a Principal, then check an action.

Order of checks: auth configured -> token present -> dev token (local only) -> Cognito token ->
database user -> role. A failure at any step stops the request before any handler runs.
"""

import secrets
from collections.abc import Callable
from contextlib import AbstractContextManager
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.engine import make_engine
from app.db.repositories import UserRepository
from app.db.session import session_scope
from app.security.jwt import (
    CognitoConfig,
    JwksKeyResolver,
    KeyResolver,
    TokenError,
    verify_access_token,
)
from app.security.permissions import Principal, authorize
from app.security.principal import build_principal, dev_principal
from app.security.roles import Action

bearer = HTTPBearer(auto_error=False)
SessionFactory = Callable[[], AbstractContextManager[Session]]
LOCAL = "local"


@lru_cache(maxsize=4)
def _engine(url: str) -> Engine:
    return make_engine(url)


@lru_cache(maxsize=2)
def _resolver(jwks_url: str) -> JwksKeyResolver:
    return JwksKeyResolver(jwks_url)


def cognito_config(settings: Settings) -> CognitoConfig | None:
    region = settings.cognito_region
    pool = settings.cognito_user_pool_id
    client = settings.cognito_app_client_id
    return CognitoConfig(region, pool, client) if region and pool and client else None


def get_session_factory() -> SessionFactory:
    def factory() -> AbstractContextManager[Session]:
        url = Settings().database_url
        if url is None:
            raise HTTPException(status_code=503, detail="Database is not configured")
        return session_scope(_engine(url.get_secret_value()))

    return factory


def get_key_resolver() -> KeyResolver | None:
    config = cognito_config(Settings())
    return None if config is None else _resolver(config.jwks_url)


def _dev_token_enabled(settings: Settings) -> bool:
    token = settings.dev_api_token
    return settings.environment == LOCAL and token is not None and bool(token.get_secret_value())


def _is_dev_token(settings: Settings, token: str) -> bool:
    expected = settings.dev_api_token.get_secret_value() if settings.dev_api_token else ""
    return _dev_token_enabled(settings) and secrets.compare_digest(token, expected)


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="Invalid credentials")


def _require_configured(settings: Settings, config: CognitoConfig | None) -> None:
    if config is None and not _dev_token_enabled(settings):
        raise HTTPException(status_code=503, detail="Authentication is not configured")


def _bearer_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None:
        raise _unauthorized()
    return credentials.credentials


def _principal_from_cognito(
    token: str, config: CognitoConfig | None, keys: KeyResolver | None, factory: SessionFactory
) -> Principal:
    if config is None or keys is None:
        raise _unauthorized()
    try:
        claims = verify_access_token(token, config, keys)
    except TokenError as error:
        raise _unauthorized() from error
    with factory() as session:
        user = UserRepository(session).get(claims.sub)
    principal = build_principal(user, claims.groups)
    if principal is None:
        raise HTTPException(status_code=403, detail="Access denied")
    return principal


def current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
    keys: Annotated[KeyResolver | None, Depends(get_key_resolver)],
) -> Principal:
    settings = Settings()
    config = cognito_config(settings)
    _require_configured(settings, config)
    token = _bearer_token(credentials)
    if _is_dev_token(settings, token):
        return dev_principal(settings)
    return _principal_from_cognito(token, config, keys, factory)


def require_action(action: Action) -> Callable[..., Principal]:
    def dependency(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
        if not authorize(principal, action).allowed:
            raise HTTPException(status_code=403, detail="Not permitted")
        return principal

    return dependency
