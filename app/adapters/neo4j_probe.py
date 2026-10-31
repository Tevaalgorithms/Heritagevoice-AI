"""The Test button for Neo4j: connect with the saved address, user and password, and write nothing.

It only asks the driver to check the connection, which proves the address is reachable and the
login works. The address must use an encrypted scheme. Returns a short safe code; provider text,
the address and the password never leave.
"""

from typing import cast

from neo4j import GraphDatabase
from pydantic import SecretStr

from app.models.llm import ProbeResult

ENCRYPTED_SCHEMES = ("neo4j+s://", "bolt+s://")
ERROR_CODES = {
    "AuthError": "bad_credentials",
    "ServiceUnavailable": "unreachable",
    "ConfigurationError": "bad_address",
}


def _code_for(error: Exception) -> str:
    return ERROR_CODES.get(type(error).__name__, "provider_error")


def _missing(uri: str | None, user: str | None, password: SecretStr | None) -> ProbeResult | None:
    if not (uri and user and password):
        return ProbeResult(ok=False, code="no_settings")
    return None if uri.startswith(ENCRYPTED_SCHEMES) else ProbeResult(ok=False, code="bad_address")


def _connected(uri: str, user: str, password: SecretStr) -> ProbeResult:
    try:
        with GraphDatabase.driver(uri, auth=(user, password.get_secret_value())) as driver:
            driver.verify_connectivity()
    except Exception as error:  # report only a short code, never provider text
        return ProbeResult(ok=False, code=_code_for(error))
    return ProbeResult(ok=True)


class Neo4jConnection:
    """Checks a Neo4j address and login."""

    def check(self, uri: str | None, user: str | None, password: SecretStr | None) -> ProbeResult:
        problem = _missing(uri, user, password)
        return problem or _connected(cast(str, uri), cast(str, user), cast(SecretStr, password))
