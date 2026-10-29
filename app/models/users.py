"""Application users. Identity comes from Cognito; role, status and membership live here."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.security.roles import Role


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class StoredUser(BaseModel):
    model_config = ConfigDict(frozen=True)
    sub: str
    role: Role
    status: UserStatus
    communities: frozenset[str]
