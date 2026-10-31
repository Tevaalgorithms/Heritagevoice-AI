"""Admin portal: keys and settings for the outside services, saved without ever being shown again.

An admin pastes an API key; the server writes it to AWS Parameter Store (encrypted) and forgets it.
The key is never returned, logged, put in the database or echoed in an error. This page only reports
whether each one is configured. Plain settings (an index name, a model name) are shown. Only the
names in `app.integrations` can be written, so the portal cannot touch the database password or the
sign-in secrets.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, SecretStr

from app.adapters.neo4j_probe import Neo4jConnection
from app.adapters.pinecone_probe import PineconeConnection
from app.api.admin import AdminContext, context_for
from app.config import Settings
from app.db.repositories import AuditRepository, ModelCatalogRepository
from app.integrations import INTEGRATIONS, Integration, Kind, resolve, valid_value
from app.models.llm import ProbeResult
from app.secrets import (
    ParameterStoreSecrets,
    SecretWriteError,
    SecretWriter,
    secrets_for,
    writer_for,
)
from app.security.roles import Action

router = APIRouter(prefix="/admin/integrations", tags=["admin"])
Ctx = Annotated[AdminContext, Depends(context_for(Action.INTEGRATION_MANAGE))]


class PineconeCheck(Protocol):
    """Checks a Pinecone key and index."""

    def check(
        self, api_key: SecretStr | None, index: str | None, dimension: int
    ) -> ProbeResult: ...


class Neo4jCheck(Protocol):
    """Checks a Neo4j address and login."""

    def check(
        self, uri: str | None, user: str | None, password: SecretStr | None
    ) -> ProbeResult: ...


def get_neo4j_check() -> Neo4jCheck:
    return Neo4jConnection()


def get_reader() -> ParameterStoreSecrets:
    return secrets_for(Settings())


def get_writer() -> SecretWriter:
    return writer_for(Settings())


def get_pinecone_check() -> PineconeCheck:
    return PineconeConnection()


@dataclass(frozen=True)
class Deps:
    """What these endpoints need, grouped for injection."""

    reader: ParameterStoreSecrets
    writer: SecretWriter


def deps(
    reader: Annotated[ParameterStoreSecrets, Depends(get_reader)],
    writer: Annotated[SecretWriter, Depends(get_writer)],
) -> Deps:
    return Deps(reader, writer)


class ItemView(BaseModel):
    """One value: whether it is set, and (for plain settings only) what it is."""

    name: str
    label: str
    kind: Kind
    help: str
    configured: bool
    value: str | None
    default: str | None
    planned: bool


class GroupView(BaseModel):
    """The values of one outside service."""

    label: str
    items: list[ItemView]


class IntegrationsOverview(BaseModel):
    """Every group, in a fixed order."""

    groups: list[GroupView]


class NewValue(BaseModel):
    """The value to save. For a secret this is the only time it is sent."""

    model_config = ConfigDict(extra="forbid")
    value: str


def _item(item: Integration, reader: ParameterStoreSecrets) -> ItemView:
    stored = reader.get(item.name)
    shown = stored.get_secret_value() if stored is not None and item.kind is Kind.SETTING else None
    return ItemView(
        name=item.name,
        label=item.label,
        kind=item.kind,
        help=item.help,
        configured=stored is not None,
        value=shown,
        default=item.default,
        planned=item.planned,
    )


def _catalog_keys(ctx: AdminContext) -> frozenset[str]:
    with ctx.factory() as session:
        return frozenset(e.key_name for e in ModelCatalogRepository(session).list_all())


def _custom_items(catalog_keys: frozenset[str]) -> list[Integration]:
    """Keys that catalogue models use beyond the built-in ones, when they may be written."""
    known = {item.name for item in INTEGRATIONS}
    found = (resolve(name, catalog_keys) for name in sorted(catalog_keys - known))
    return [item for item in found if item is not None]


def _all_items(catalog_keys: frozenset[str]) -> list[Integration]:
    return [*INTEGRATIONS, *_custom_items(catalog_keys)]


@router.get("")
def overview(ctx: Ctx, d: Annotated[Deps, Depends(deps)]) -> IntegrationsOverview:
    groups: dict[str, list[ItemView]] = defaultdict(list)
    for item in _all_items(_catalog_keys(ctx)):
        groups[item.group].append(_item(item, d.reader))
    return IntegrationsOverview(groups=[GroupView(label=g, items=v) for g, v in groups.items()])


def _problem(code: str, status: int) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code})


@router.put("/{name}")
def save(name: str, body: NewValue, ctx: Ctx, d: Annotated[Deps, Depends(deps)]) -> ItemView:
    """Save a value. Secrets are encrypted at rest and never shown again."""
    item = resolve(name, _catalog_keys(ctx))
    if item is None:
        raise _problem("unknown_integration", 404)
    if not valid_value(body.value):
        raise _problem("invalid_value", 422)
    try:
        d.writer.put(item.name, body.value, item.kind is Kind.SECRET)
    except SecretWriteError as error:
        raise _problem(error.code, 503) from error
    d.reader.forget(item.name)
    with ctx.factory() as session:
        entry = ctx.entry("integration:set", f"integration:{item.name}", item.kind.value)
        AuditRepository(session).record(entry)
    return _item(item, d.reader)


@router.post("/pinecone/test")
def test_pinecone(
    ctx: Ctx,
    d: Annotated[Deps, Depends(deps)],
    probe: Annotated[PineconeCheck, Depends(get_pinecone_check)],
) -> ProbeResult:
    """Look the index up with the saved key. Writes nothing."""
    settings = Settings()
    dimension = d.reader.get("EMBEDDING_DIMENSION")
    size = int(dimension.get_secret_value()) if dimension else settings.embedding_dimension
    return probe.check(d.reader.get("PINECONE_API_KEY"), _setting(d.reader, "PINECONE_INDEX"), size)


def _setting(reader: ParameterStoreSecrets, name: str) -> str | None:
    value = reader.get(name)
    return value.get_secret_value() if value else None


@router.post("/neo4j/test")
def test_neo4j(
    ctx: Ctx,
    d: Annotated[Deps, Depends(deps)],
    probe: Annotated[Neo4jCheck, Depends(get_neo4j_check)],
) -> ProbeResult:
    """Connect with the saved address, user and password. Writes nothing."""
    uri, user = _setting(d.reader, "NEO4J_URI"), _setting(d.reader, "NEO4J_USERNAME")
    return probe.check(uri, user, d.reader.get("NEO4J_PASSWORD"))
