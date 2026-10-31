"""Amazon Cognito account administration. Thin on purpose: every call is one boto3 request.

The pool uses email as the sign-in name, so a user's Cognito username is their subject ID.
"""

from collections.abc import Iterator
from typing import Any

import boto3

from app.models.users import Signup
from app.security.roles import Role

ROLE_GROUPS = {role.value for role in Role}
MAX_PAGES = 10  # 600 accounts: enough to show who is waiting; the rest appear as these are handled


class CognitoIdentityProvider:
    """Amazon Cognito user administration: invite a user, change their group, disable them."""

    def __init__(self, region: str, user_pool_id: str, client: Any | None = None) -> None:
        self._pool = user_pool_id
        self._client = client or boto3.client("cognito-idp", region_name=region)

    def invite_user(self, email: str, role: Role) -> str:
        response = self._client.admin_create_user(
            UserPoolId=self._pool,
            Username=email,
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
            ],
            DesiredDeliveryMediums=["EMAIL"],
        )
        sub = _attribute(response["User"]["Attributes"], "sub")
        self.set_role(sub, role)
        return sub

    def set_role(self, sub: str, role: Role) -> None:
        groups = self._client.admin_list_groups_for_user(UserPoolId=self._pool, Username=sub)
        current = {g["GroupName"] for g in groups["Groups"]} & ROLE_GROUPS
        for group in current - {role.value}:
            self._client.admin_remove_user_from_group(
                UserPoolId=self._pool, Username=sub, GroupName=group
            )
        if role.value not in current:
            self._client.admin_add_user_to_group(
                UserPoolId=self._pool, Username=sub, GroupName=role.value
            )

    def disable_user(self, sub: str) -> None:
        self._client.admin_disable_user(UserPoolId=self._pool, Username=sub)
        self._client.admin_user_global_sign_out(UserPoolId=self._pool, Username=sub)

    def list_signups(self) -> list[Signup]:
        users = (user for page in self._pages() for user in page["Users"])
        return [signup for user in users if (signup := _signup(user)) is not None]

    def find_sub(self, email: str) -> str | None:
        user = self._lookup("email", email)
        return None if user is None else _attribute(user["Attributes"], "sub")

    def email_of(self, sub: str) -> str | None:
        user = self._lookup("sub", sub)
        return None if user is None else _attribute(user["Attributes"], "email")

    def _lookup(self, attribute: str, value: str) -> dict[str, Any] | None:
        """One account matching `attribute = value`. The value is quoted, never concatenated raw."""
        quoted = value.replace("\\", "\\\\").replace('"', '\\"')
        page = self._client.list_users(
            UserPoolId=self._pool, Filter=f'{attribute} = "{quoted}"', Limit=1
        )
        users = page.get("Users", [])
        return users[0] if users else None

    def _pages(self) -> Iterator[dict[str, Any]]:
        token: str | None = None
        for _ in range(MAX_PAGES):
            extra = {"PaginationToken": token} if token else {}
            page = self._client.list_users(UserPoolId=self._pool, Limit=60, **extra)
            yield page
            token = page.get("PaginationToken")
            if not token:
                return


def _signup(user: dict[str, Any]) -> Signup | None:
    """Only confirmed, enabled accounts whose email was verified."""
    attributes = user.get("Attributes", [])
    verified = {a["Name"]: a["Value"] for a in attributes}.get("email_verified")
    if user.get("UserStatus") != "CONFIRMED" or not user.get("Enabled") or verified != "true":
        return None
    return Signup(
        sub=_attribute(attributes, "sub"),
        email=_attribute(attributes, "email"),
        created=user["UserCreateDate"].date().isoformat(),
    )


def _attribute(attributes: list[dict[str, str]], name: str) -> str:
    return next(a["Value"] for a in attributes if a["Name"] == name)
