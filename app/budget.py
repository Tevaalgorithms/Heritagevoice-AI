"""A spending guard-rail: a monthly limit in US dollars, spent as an equal share each day.

An admin sets one monthly figure on the Settings page. Each day may use that figure divided by the
number of days in the month, so a busy day cannot eat the whole month. Before every language-model
call the guard adds up today's estimated cost (the day runs on UTC) and refuses the call once the
day's share is spent. The estimate uses the prices entered on the Models tab, so a model with no
price is counted as free and the Settings page says so. Only numbers are read; nothing about a
question or a recording.
"""

import calendar
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from app.db.repositories.model_settings import ModelCatalogRepository
from app.db.repositories.usage import CostLimitRepository, UsageRepository
from app.errors import ProviderError
from app.usage import SessionFactory, UsageLog, summarise

BUDGET = "budget"


class BudgetExceededError(ProviderError):
    """Today's share of the monthly limit is spent, so no more model calls are made today."""

    def __init__(self) -> None:
        super().__init__("daily cost limit reached", code=BUDGET)


class BudgetStatus(BaseModel):
    """Where today stands against the limit. `monthly_usd` is None when no limit is set."""

    model_config = ConfigDict(frozen=True)
    monthly_usd: float | None
    daily_usd: float | None
    spent_today: float
    remaining_today: float | None
    exhausted: bool
    unpriced_models: list[str]


def daily_share(monthly_usd: float, now: datetime) -> float:
    """One day's part of the monthly limit, for the month that `now` falls in."""
    return monthly_usd / calendar.monthrange(now.year, now.month)[1]


@dataclass(frozen=True)
class Spending:
    """What today's model calls have cost so far, and which models had no price."""

    cost: float
    unpriced: list[str]


def _spent(sessions: SessionFactory, now: datetime) -> Spending:
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    with sessions() as session:
        totals = UsageRepository(session).totals_since(start)
        catalog = ModelCatalogRepository(session).list_all()
    summary = summarise(totals, catalog, 1)
    return Spending(summary.cost, summary.unpriced_models)


def budget_status(sessions: SessionFactory, now: datetime | None = None) -> BudgetStatus:
    """Today's spending against the daily share of the monthly limit."""
    moment = now or datetime.now(UTC)
    with sessions() as session:
        monthly = CostLimitRepository(session).get()
    spent = _spent(sessions, moment)
    daily = None if monthly is None else daily_share(monthly, moment)
    return BudgetStatus(
        monthly_usd=monthly,
        daily_usd=daily,
        spent_today=spent.cost,
        remaining_today=None if daily is None else max(round(daily - spent.cost, 4), 0.0),
        exhausted=daily is not None and spent.cost >= daily,
        unpriced_models=spent.unpriced,
    )


def check_budget(sessions: SessionFactory) -> None:
    """Raise `BudgetExceededError` when today's share is spent; do nothing when no limit is set."""
    if budget_status(sessions).exhausted:
        raise BudgetExceededError


class GuardedUsageLog(UsageLog):
    """The usage log that also stops a model call once the day's share of the limit is spent."""

    def check(self) -> None:
        check_budget(self._sessions)
