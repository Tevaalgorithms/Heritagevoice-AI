"""Token usage per model call. Rows hold counts only, never prompts or answers."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.tables import ModelUsageRow
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
        since = datetime.now(UTC) - timedelta(days=days)
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
