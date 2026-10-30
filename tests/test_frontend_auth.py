from types import SimpleNamespace

import pytest

from app.config import Settings
from frontend.auth import cognito_enabled, dev_token, resolve_token, user_access_token


def settings(**values):
    return Settings(_env_file=None, **values)


def signed_in(access="cognito-access-token"):
    return SimpleNamespace(is_logged_in=True, tokens={"id": "id-token", "access": access})


def signed_out():
    return SimpleNamespace(is_logged_in=False, tokens={})


def test_the_dev_token_is_used_only_in_the_local_environment():
    assert dev_token(settings(dev_api_token="dev-value", environment="local")) == "dev-value"
    assert dev_token(settings(dev_api_token="dev-value", environment="production")) is None
    assert dev_token(settings(environment="local")) is None


def test_a_signed_in_user_forwards_the_access_token_never_the_id_token():
    assert user_access_token(signed_in()) == "cognito-access-token"


@pytest.mark.parametrize(
    "user",
    [signed_out(), SimpleNamespace(is_logged_in=True, tokens={"id": "x"}), SimpleNamespace()],
    ids=["signed-out", "access-token-not-exposed", "no-user-info"],
)
def test_no_access_token_means_no_token(user):
    assert user_access_token(user) is None


def test_the_dev_token_wins_locally_and_cognito_wins_elsewhere():
    local = settings(dev_api_token="dev-value", environment="local")
    prod = settings(dev_api_token="dev-value", environment="production")
    assert resolve_token(local, signed_in()) == "dev-value"
    assert resolve_token(prod, signed_in()) == "cognito-access-token"
    assert resolve_token(prod, signed_out()) is None


def test_cognito_is_enabled_only_when_fully_configured():
    full = settings(cognito_region="r", cognito_user_pool_id="p", cognito_app_client_id="c")
    assert cognito_enabled(full)
    assert not cognito_enabled(settings(cognito_region="r", cognito_user_pool_id="p"))


def test_streamlit_sign_in_has_the_authlib_it_needs():
    """Without it st.login raises StreamlitMissingAuthlibError and sign-in breaks."""
    import authlib  # noqa: PLC0415

    assert authlib.__version__
