"""Pick the bearer token the UI sends to the API.

Local development uses the dev token. Everywhere else the user signs in with Amazon Cognito
(Streamlit's built-in OIDC login) and we forward their access token. Tokens stay in the
Streamlit server session: never in URLs, logs or browser-visible widgets.
"""

from typing import Any

from app.config import Settings

COGNITO_PROVIDER = "cognito"
LOCAL = "local"


def cognito_enabled(settings: Settings) -> bool:
    return bool(
        settings.cognito_region and settings.cognito_user_pool_id and settings.cognito_app_client_id
    )


def dev_token(settings: Settings) -> str | None:
    secret = settings.dev_api_token
    value = secret.get_secret_value() if secret else ""
    return value if settings.environment == LOCAL and value else None


def user_access_token(user: Any) -> str | None:
    if not getattr(user, "is_logged_in", False):
        return None
    try:
        return str(user.tokens["access"])
    except (KeyError, AttributeError):
        return None


def resolve_token(settings: Settings, user: Any) -> str | None:
    return dev_token(settings) or user_access_token(user)
