"""Application users. Identity comes from Cognito; role, status and membership live here."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.security.roles import Role


class UserStatus(StrEnum):
    """Whether a user may sign in."""

    ACTIVE = "active"
    DISABLED = "disabled"


class Signup(BaseModel):
    """Someone who created an account themselves and confirmed their email, not yet approved."""

    model_config = ConfigDict(frozen=True)
    sub: str
    email: str
    created: str


class StoredUser(BaseModel):
    """A user as stored: role, status and communities."""

    model_config = ConfigDict(frozen=True)
    sub: str
    role: Role
    status: UserStatus
    communities: frozenset[str]
    created: str = ""  # the day the record was made, YYYY-MM-DD
