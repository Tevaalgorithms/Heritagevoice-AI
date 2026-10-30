"""Users and their community memberships."""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.tables import (
    AppUserRow,
    CommunityMemberRow,
)
from app.models.users import StoredUser, UserStatus
from app.security.roles import Role


class UserRepository:
    """Stores users, their roles, status and community memberships."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, sub: str, role: Role, communities: frozenset[str]) -> StoredUser:
        self._session.add(AppUserRow(sub=sub, role=role, status=UserStatus.ACTIVE))
        self._session.flush()
        self.set_communities(sub, communities)
        return self._require(sub)

    def known(self, subs: list[str]) -> set[str]:
        """Which of these accounts already have a record here."""
        query = select(AppUserRow.sub).where(AppUserRow.sub.in_(subs))
        return set(self._session.scalars(query))

    def get(self, sub: str) -> StoredUser | None:
        row = self._session.get(AppUserRow, sub)
        return None if row is None else self._to_user(row)

    def set_role(self, sub: str, role: Role) -> None:
        self._row(sub).role = role

    def set_status(self, sub: str, status: UserStatus) -> None:
        self._row(sub).status = status

    def set_communities(self, sub: str, communities: frozenset[str]) -> None:
        self._row(sub)
        self._session.execute(delete(CommunityMemberRow).where(CommunityMemberRow.user_sub == sub))
        self._session.add_all(CommunityMemberRow(user_sub=sub, community_id=c) for c in communities)
        self._session.flush()

    def _row(self, sub: str) -> AppUserRow:
        row = self._session.get(AppUserRow, sub)
        if row is None:
            raise KeyError(sub)
        return row

    def _require(self, sub: str) -> StoredUser:
        return self._to_user(self._row(sub))

    def _to_user(self, row: AppUserRow) -> StoredUser:
        query = select(CommunityMemberRow.community_id).where(
            CommunityMemberRow.user_sub == row.sub
        )
        communities = frozenset(self._session.scalars(query))
        return StoredUser(
            sub=row.sub,
            role=Role(row.role),
            status=UserStatus(row.status),
            communities=communities,
        )
