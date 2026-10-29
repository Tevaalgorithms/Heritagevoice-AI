"""Create the first admin account record.

After inviting yourself in the Cognito console (and adding yourself to the `admin` group), copy
your user's `sub` and run:  uv run python -m app.bootstrap --sub <sub>
Safe to repeat: an existing user is left unchanged.
"""

import argparse
import re
from collections.abc import Sequence

from sqlalchemy import Engine

from app.config import Settings
from app.db.engine import engine_from_settings
from app.db.repositories import UserRepository
from app.db.session import session_scope
from app.security.roles import Role

SUB_PATTERN = re.compile(r"[A-Za-z0-9-]{1,64}")


def create_first_admin(engine: Engine, sub: str) -> bool:
    """Return True if the admin was created, False if the user already existed."""
    if not SUB_PATTERN.fullmatch(sub):
        raise ValueError("sub must be 1-64 letters, digits or hyphens")
    with session_scope(engine) as session:
        users = UserRepository(session)
        if users.get(sub) is not None:
            return False
        users.create(sub, Role.ADMIN, frozenset())
        return True


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Create the first HeritageVoice admin record")
    parser.add_argument("--sub", required=True, help="the Cognito `sub` of the admin user")
    args = parser.parse_args(argv)
    created = create_first_admin(engine_from_settings(Settings()), args.sub)
    print("admin created" if created else "user already exists; nothing changed")


if __name__ == "__main__":
    main()
