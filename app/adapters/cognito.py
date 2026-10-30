"""Amazon Cognito account administration. Thin on purpose: every call is one boto3 request.

The pool uses email as the sign-in name, so a user's Cognito username is their subject ID.
"""

from typing import Any

import boto3

from app.security.roles import Role

ROLE_GROUPS = {role.value for role in Role}


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


def _attribute(attributes: list[dict[str, str]], name: str) -> str:
    return next(a["Value"] for a in attributes if a["Name"] == name)
