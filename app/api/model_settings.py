"""Admin model settings: the model catalogue, and per job a primary model plus fall-backs.

API keys are NOT handled here. The catalogue stores each model's key *name*; the value lives in
AWS Parameter Store (SecureString) and is read by the server when needed. This API only reports
whether each key is configured; it never reads out, accepts or stores a key value.
"""

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.adapters.model_tester import AnthropicModelTester
from app.api.admin import AdminContext, context_for
from app.config import Settings
from app.db.repositories import AuditRepository, ModelCatalogRepository, ModelSettingRepository
from app.model_registry import default_setting
from app.models.llm import (
    CatalogEntry,
    ModelParams,
    ModelRole,
    ModelSetting,
    ModelStatus,
    NewModel,
    ProbeResult,
    StatusChange,
)
from app.ports import ModelTester
from app.secrets import SecretReader, secrets_for
from app.security.roles import Action

router = APIRouter(prefix="/admin/models", tags=["admin"])
Ctx = Annotated[AdminContext, Depends(context_for(Action.MODEL_MANAGE))]


def get_model_tester() -> ModelTester:
    return AnthropicModelTester()


def get_secrets() -> SecretReader:
    return secrets_for(Settings())


Secrets = Annotated[SecretReader, Depends(get_secrets)]


@dataclass(frozen=True)
class ProbeDeps:
    """The tester and secret reader the Test button needs, grouped for injection."""

    tester: ModelTester
    secrets: SecretReader


def probe_deps(
    tester: Annotated[ModelTester, Depends(get_model_tester)], secrets: Secrets
) -> ProbeDeps:
    return ProbeDeps(tester, secrets)


class CatalogView(BaseModel):
    """A catalogue model as shown to admins, with whether its key is configured."""

    model_id: str
    provider: str
    key_name: str
    status: ModelStatus
    key_configured: bool


class ModelView(BaseModel):
    """The model setting in force for one job."""

    role: ModelRole
    provider: str
    model: str
    temperature: float
    timeout_s: float
    max_retries: int
    fallbacks: list[str]
    source: Literal["database", "default"]


class ModelsOverview(BaseModel):
    """Everything the Settings page needs: the catalogue and each job's setting."""

    catalog: list[CatalogView]
    roles: list[ModelView]


def _view(setting: ModelSetting, source: Literal["database", "default"]) -> ModelView:
    data = setting.model_dump(mode="json")
    return ModelView(**{**data, "fallbacks": list(setting.fallbacks)}, source=source)


def _catalog_view(entry: CatalogEntry, secrets: SecretReader) -> CatalogView:
    return CatalogView(
        **entry.model_dump(mode="json"), key_configured=secrets.is_configured(entry.key_name)
    )


def _problem(code: str, status: int = 422) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code})


@router.get("")
def overview(ctx: Ctx, secrets: Secrets) -> ModelsOverview:
    settings = Settings()
    with ctx.factory() as session:
        saved = {s.role: s for s in ModelSettingRepository(session).list_all()}
        catalog = ModelCatalogRepository(session).list_all()
    roles = [
        _view(saved[r], "database")
        if r in saved
        else _view(default_setting(r, settings), "default")
        for r in ModelRole
    ]
    return ModelsOverview(catalog=[_catalog_view(e, secrets) for e in catalog], roles=roles)


@router.post("/catalog", status_code=201)
def add_model(body: NewModel, ctx: Ctx, secrets: Secrets) -> CatalogView:
    with ctx.factory() as session:
        entry = ModelCatalogRepository(session).add(body, ctx.admin.user_id)
        if entry is None:
            raise _problem("model_exists", 409)
        detail = f"{body.provider.value}/{body.model_id} key={body.key_name}"
        AuditRepository(session).record(ctx.entry("model:add", f"model:{body.model_id}", detail))
    return _catalog_view(entry, secrets)


@router.put("/catalog/{model_id}")
def set_status(model_id: str, body: StatusChange, ctx: Ctx, secrets: Secrets) -> CatalogView:
    with ctx.factory() as session:
        entry = ModelCatalogRepository(session).set_status(model_id, body.status)
        if entry is None:
            raise _problem("unknown_model", 404)
        AuditRepository(session).record(
            ctx.entry("model:status", f"model:{model_id}", body.status.value)
        )
    return _catalog_view(entry, secrets)


def _check_chain(params: ModelParams, catalog: list[CatalogEntry]) -> None:
    """Every model in the chain must be an active catalogue model."""
    active = {e.model_id for e in catalog if e.status is ModelStatus.ACTIVE}
    if not set(params.chain()) <= active:
        raise _problem("model_not_available")


@router.put("/{role}")
def save(role: ModelRole, body: ModelParams, ctx: Ctx) -> ModelView:
    with ctx.factory() as session:
        _check_chain(body, ModelCatalogRepository(session).list_all())
        saved = ModelSettingRepository(session).upsert(role, body, ctx.admin.user_id)
        detail = f"{body.provider.value}/{' > '.join(body.chain())}"
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
    role: ModelRole, body: ModelParams, ctx: Ctx, probe: Annotated[ProbeDeps, Depends(probe_deps)]
) -> ProbeResult:
    """Send one tiny request with the primary model of these settings (costs a few tokens)."""
    with ctx.factory() as session:
        entry = ModelCatalogRepository(session).get(body.model)
    if entry is None:
        return ProbeResult(ok=False, code="unknown_model")
    return probe.tester.check(body, probe.secrets.get(entry.key_name))
