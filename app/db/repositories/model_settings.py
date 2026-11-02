"""The model catalogue and the per-job model settings (names of keys only, never values)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.tables import (
    ModelCatalogRow,
    ModelSettingRow,
)
from app.models.llm import (
    CatalogEntry,
    ModelParams,
    ModelRole,
    ModelSetting,
    ModelStatus,
    NewModel,
    PriceChange,
    Provider,
)


def _to_setting(row: ModelSettingRow) -> ModelSetting:
    return ModelSetting(
        role=ModelRole(row.role),
        provider=Provider(row.provider),
        model=row.model,
        temperature=row.temperature,
        timeout_s=row.timeout_s,
        max_retries=row.max_retries,
        fallbacks=tuple(row.fallbacks or ()),
    )


def _to_entry(row: ModelCatalogRow) -> CatalogEntry:
    return CatalogEntry(
        model_id=row.model_id,
        provider=Provider(row.provider),
        key_name=row.key_name,
        status=ModelStatus(row.status),
        input_price=row.input_price,
        output_price=row.output_price,
    )


class ModelCatalogRepository:
    """The approved models and their statuses."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_all(self) -> list[CatalogEntry]:
        rows = self._session.scalars(select(ModelCatalogRow).order_by(ModelCatalogRow.model_id))
        return [_to_entry(r) for r in rows]

    def get(self, model_id: str) -> CatalogEntry | None:
        row = self._session.get(ModelCatalogRow, model_id)
        return None if row is None else _to_entry(row)

    def add(self, model: NewModel, created_by: str) -> CatalogEntry | None:
        """None when the model is already in the catalogue (deprecate it instead)."""
        if self._session.get(ModelCatalogRow, model.model_id) is not None:
            return None
        row = ModelCatalogRow(
            model_id=model.model_id,
            provider=model.provider.value,
            key_name=model.resolved_key_name(),
            created_by=created_by,
        )
        self._session.add(row)
        self._session.flush()
        return _to_entry(row)

    def set_status(self, model_id: str, status: ModelStatus) -> CatalogEntry | None:
        row = self._session.get(ModelCatalogRow, model_id)
        if row is None:
            return None
        row.status = status.value
        self._session.flush()
        return _to_entry(row)

    def set_price(self, model_id: str, price: PriceChange) -> CatalogEntry | None:
        row = self._session.get(ModelCatalogRow, model_id)
        if row is None:
            return None
        row.input_price, row.output_price = price.input_price, price.output_price
        self._session.flush()
        return _to_entry(row)


class ModelSettingRepository:
    """The saved model setting for each job."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, role: ModelRole) -> ModelSetting | None:
        row = self._session.get(ModelSettingRow, role.value)
        return None if row is None else _to_setting(row)

    def list_all(self) -> list[ModelSetting]:
        return [_to_setting(r) for r in self._session.scalars(select(ModelSettingRow))]

    def upsert(self, role: ModelRole, params: ModelParams, updated_by: str) -> ModelSetting:
        values = {**params.model_dump(mode="json"), "updated_by": updated_by}
        row = self._session.get(ModelSettingRow, role.value)
        if row is None:
            row = ModelSettingRow(role=role.value, **values)
            self._session.add(row)
        else:
            for name, value in values.items():
                setattr(row, name, value)
        self._session.flush()
        return _to_setting(row)

    def delete(self, role: ModelRole) -> bool:
        row = self._session.get(ModelSettingRow, role.value)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True
