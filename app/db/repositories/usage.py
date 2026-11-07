"""Token usage per model call. Rows hold counts only, never prompts or answers."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.tables import CostLimitRow, ModelUsageRow
from app.models.usage import UsageTotal


class UsageRepository:
    """Records each model call and adds them up for the admin."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, role: str, model: str, input_tokens: int, output_tokens: int) -> None:
        self._session.add(
            ModelUsageRow(
                role=role, model=model, input_tokens=input_tokens, output_tokens=output_tokens
            )
        )
        self._session.flush()

    def totals(self, days: int) -> list[UsageTotal]:
        return self.totals_since(datetime.now(UTC) - timedelta(days=days))

    def totals_since(self, since: datetime) -> list[UsageTotal]:
        query = (
            select(
                ModelUsageRow.role,
                ModelUsageRow.model,
                func.count(),
                func.sum(ModelUsageRow.input_tokens),
                func.sum(ModelUsageRow.output_tokens),
            )
            .where(ModelUsageRow.at >= since)
            .group_by(ModelUsageRow.role, ModelUsageRow.model)
            .order_by(ModelUsageRow.role, ModelUsageRow.model)
        )
        return [
            UsageTotal(role=r, model=m, calls=c, input_tokens=i or 0, output_tokens=o or 0)
            for r, m, c, i, o in self._session.execute(query)
        ]


class CostLimitRepository:
    """The monthly spending limit. One value for the whole site; none means no limit."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self) -> float | None:
        row = self._session.get(CostLimitRow, 1)
        return None if row is None else row.monthly_usd

    def set(self, monthly_usd: float | None, updated_by: str) -> None:
        row = self._session.get(CostLimitRow, 1)
        if monthly_usd is None:
            if row is not None:
                self._session.delete(row)
        elif row is None:
            self._session.add(CostLimitRow(monthly_usd=monthly_usd, updated_by=updated_by))
        else:
            row.monthly_usd, row.updated_by = monthly_usd, updated_by
            row.updated_at = datetime.now(UTC)
        self._session.flush()
