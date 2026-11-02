"""Admin usage: tokens and an estimated cost per job and model. Admin role only; numbers only."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.admin import AdminContext, context_for
from app.db.repositories import ModelCatalogRepository, UsageRepository
from app.models.usage import UsageSummary
from app.security.roles import Action
from app.usage import summarise

router = APIRouter(prefix="/admin/usage", tags=["admin"])
Ctx = Annotated[AdminContext, Depends(context_for(Action.MODEL_MANAGE))]
Days = Annotated[int, Query(ge=1, le=365)]


@router.get("")
def usage(ctx: Ctx, days: Days = 30) -> UsageSummary:
    """Calls, tokens and estimated cost over the last `days` days."""
    with ctx.factory() as session:
        totals = UsageRepository(session).totals(days)
        catalog = ModelCatalogRepository(session).list_all()
    return summarise(totals, catalog, days)
