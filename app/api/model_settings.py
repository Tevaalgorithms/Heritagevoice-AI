"""Admin model settings: which model each job uses, with a Test button.

API keys are NOT handled here. They live in AWS Parameter Store (SecureString) and reach the app
as the environment variable HERITAGEVOICE_LLM_API_KEY. This page can only say whether a key is
configured; it never reads, shows, stores or accepts one.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.adapters.model_tester import AnthropicModelTester
from app.api.admin import AdminContext, context_for
from app.config import Settings
from app.db.repositories import AuditRepository, ModelSettingRepository
from app.model_registry import default_setting
from app.models.llm import ALLOWED_MODELS, ModelParams, ModelRole, ModelSetting, ProbeResult
from app.ports import ModelTester
from app.security.roles import Action

router = APIRouter(prefix="/admin/models", tags=["admin"])
Ctx = Annotated[AdminContext, Depends(context_for(Action.MODEL_MANAGE))]
KEY_NAME = "HERITAGEVOICE_LLM_API_KEY"


def get_model_tester() -> ModelTester:
    return AnthropicModelTester(Settings().llm_api_key)


class ModelView(BaseModel):
    role: ModelRole
    provider: str
    model: str
    temperature: float
    timeout_s: float
    max_retries: int
    source: Literal["database", "default"]


class ModelsOverview(BaseModel):
    key_configured: bool
    key_name: str
    allowed: dict[str, list[str]]
    roles: list[ModelView]


def _view(setting: ModelSetting, source: Literal["database", "default"]) -> ModelView:
    return ModelView(**setting.model_dump(mode="json"), source=source)


def _key_configured(settings: Settings) -> bool:
    key = settings.llm_api_key
    return key is not None and bool(key.get_secret_value())


@router.get("")
def overview(ctx: Ctx) -> ModelsOverview:
    settings = Settings()
    with ctx.factory() as session:
        saved = {s.role: s for s in ModelSettingRepository(session).list_all()}
    roles = [
        _view(saved[r], "database")
        if r in saved
        else _view(default_setting(r, settings), "default")
        for r in ModelRole
    ]
    return ModelsOverview(
        key_configured=_key_configured(settings),
        key_name=KEY_NAME,
        allowed={p.value: list(models) for p, models in ALLOWED_MODELS.items()},
        roles=roles,
    )


@router.put("/{role}")
def save(role: ModelRole, body: ModelParams, ctx: Ctx) -> ModelView:
    with ctx.factory() as session:
        saved = ModelSettingRepository(session).upsert(role, body, ctx.admin.user_id)
        detail = f"{body.provider.value}/{body.model}"
        AuditRepository(session).record(ctx.entry("model:update", f"model:{role.value}", detail))
    return _view(saved, "database")


@router.delete("/{role}")
def reset(role: ModelRole, ctx: Ctx) -> ModelView:
    """Remove the saved setting so the environment default applies again."""
    with ctx.factory() as session:
        ModelSettingRepository(session).delete(role)
        AuditRepository(session).record(ctx.entry("model:reset", f"model:{role.value}"))
    return _view(default_setting(role, Settings()), "default")


@router.post("/{role}/test")
def test(
    role: ModelRole,
    body: ModelParams,
    ctx: Ctx,
    tester: Annotated[ModelTester, Depends(get_model_tester)],
) -> ProbeResult:
    """Send one tiny request with these settings (costs a few tokens); nothing is saved."""
    return tester.check(body)
