import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.security.jwt import CognitoConfig, TokenError, verify_access_token

CONFIG = CognitoConfig(region="eu-west-2", user_pool_id="eu-west-2_TESTPOOL", client_id="client-1")
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class StaticKeys:
    def signing_key(self, token):
        return KEY.public_key()


def make_token(key=KEY, algorithm="RS256", **overrides):
    claims = {
        "sub": "user-sub-1",
        "iss": CONFIG.issuer,
        "client_id": CONFIG.client_id,
        "token_use": "access",
        "cognito:groups": ["reviewer"],
        "exp": int(time.time()) + 600,
    }
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm=algorithm)


def verify(token):
    return verify_access_token(token, CONFIG, StaticKeys())


def test_a_valid_access_token_yields_sub_and_groups():
    claims = verify(make_token())
    assert (claims.sub, claims.groups) == ("user-sub-1", frozenset({"reviewer"}))


def test_a_token_without_groups_has_an_empty_group_set():
    assert verify(make_token(**{"cognito:groups": None})).groups == frozenset()


@pytest.mark.parametrize(
    "token",
    [
        make_token(exp=int(time.time()) - 10),
        make_token(iss="https://cognito-idp.eu-west-2.amazonaws.com/other-pool"),
        make_token(client_id="another-client"),
        make_token(client_id=None),
        make_token(token_use="id"),
        make_token(token_use=None),
        make_token(sub=None),
        make_token(exp=None),
        make_token(key=OTHER_KEY),
        "not-a-token",
        "",
    ],
    ids=[
        "expired",
        "wrong-issuer",
        "wrong-client",
        "missing-client",
        "id-token",
        "missing-token-use",
        "missing-sub",
        "missing-exp",
        "wrong-signature",
        "garbage",
        "empty",
    ],
)
def test_bad_tokens_are_rejected(token):
    with pytest.raises(TokenError):
        verify(token)


def test_tokens_signed_with_another_algorithm_are_rejected():
    forged = make_token(key="shared-secret-shared-secret-12345", algorithm="HS256")
    with pytest.raises(TokenError):
        verify(forged)


def test_unsigned_tokens_are_rejected():
    unsigned = jwt.encode({"sub": "x", "iss": CONFIG.issuer}, key=None, algorithm="none")
    with pytest.raises(TokenError):
        verify(unsigned)


def test_the_jwks_url_and_issuer_are_derived_from_the_pool():
    assert CONFIG.issuer.endswith("/eu-west-2_TESTPOOL")
    assert CONFIG.jwks_url.endswith("/.well-known/jwks.json")
