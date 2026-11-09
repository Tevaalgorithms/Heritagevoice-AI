"""Admin cost limit: one monthly figure in US dollars that caps each day's model spending.

Admin role only. The page shows today's spending against the day's share; setting the limit to
nothing removes it. Numbers only: no questions, answers or recordings pass through here.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.admin import AdminContext, context_for
from app.budget import BudgetStatus, budget_status
from app.db.repositories import AuditRepository, CostLimitRepository
from app.security.roles import Action

router = APIRouter(prefix="/admin/budget", tags=["admin"])
Ctx = Annotated[AdminContext, Depends(context_for(Action.MODEL_MANAGE))]


class LimitChange(BaseModel):
    """The new monthly limit in US dollars, or None to remove the limit."""

    monthly_usd: Annotated[float, Field(gt=0, le=1_000_000)] | None


@router.get("")
def status(ctx: Ctx) -> BudgetStatus:
    """The limit, today's share of it, what has been spent today and what is left."""
    return budget_status(ctx.factory)


@router.put("")
def change(body: LimitChange, ctx: Ctx) -> BudgetStatus:
    with ctx.factory() as session:
        CostLimitRepository(session).set(body.monthly_usd, ctx.admin.user_id)
        detail = "removed" if body.monthly_usd is None else f"monthly_usd={body.monthly_usd:g}"
        AuditRepository(session).record(ctx.entry("budget:set", "budget", detail))
    return budget_status(ctx.factory)
