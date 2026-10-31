"""Groups (communities): a friendly name for each ID that consents and memberships refer to."""

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.db.tables import CommunityRow
from app.models.groups import Group, slugify


def _to_group(row: CommunityRow) -> Group:
    return Group(id=row.id, name=row.name)


class CommunityRepository:
    """Stores groups. Creating one picks a free ID from the name."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, name: str, created_by: str) -> Group:
        group_id = self._free_id(slugify(name))
        self._session.add(CommunityRow(id=group_id, name=name, created_by=created_by))
        self._session.flush()
        return Group(id=group_id, name=name)

    def all(self) -> list[Group]:
        return self._groups(select(CommunityRow).order_by(CommunityRow.name))

    def among(self, ids: list[str]) -> list[Group]:
        """The named groups with these IDs. An ID with no name is left out."""
        query = select(CommunityRow).where(CommunityRow.id.in_(ids)).order_by(CommunityRow.name)
        return self._groups(query)

    def _groups(self, query: Select[CommunityRow]) -> list[Group]:
        return [_to_group(row) for row in self._session.scalars(query)]

    def _free_id(self, base: str) -> str:
        query = select(CommunityRow.id).where(CommunityRow.id.like(f"{base}%"))
        taken = set(self._session.scalars(query))
        candidates = (base, *(f"{base}-{n}" for n in range(2, len(taken) + 3)))
        return next(c for c in candidates if c not in taken)
