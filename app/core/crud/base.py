"""Small, async CRUD helpers for SQLModel tables."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import inspect, select
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.base import utc_now


@dataclass(frozen=True)
class PageResult[ItemT]:
    """One bounded offset page and the exact continuation offset, if any."""

    items: Sequence[ItemT]
    next_offset: int | None


class SQLModelCRUD[ModelT: SQLModel, CreateSchemaT: BaseModel, UpdateSchemaT: BaseModel]:
    """FastCRUD-style SQLModel operations with explicit scope and mutation rules.

    Methods intentionally mirror familiar CRUD names: ``get``, ``get_multi``,
    ``create``, ``update``, and ``delete``. Calls flush but never commit; the
    owning service chooses the transaction boundary.

    ``scope`` is applied to every read and checked before every mutation.
    Supplying ``soft_delete_field="deleted_at"`` turns ``delete`` into a soft
    delete and hides deleted records from reads.
    """

    def __init__(
        self,
        model: type[ModelT],
        session: AsyncSession,
        *,
        scope: Mapping[str, Any] | None = None,
        mutable_fields: frozenset[str] = frozenset(),
        id_field: str = "id",
        soft_delete_field: str | None = None,
    ) -> None:
        self.model = model
        self.session = session
        self.scope = dict(scope or {})
        self.id_field = id_field
        self.soft_delete_field = soft_delete_field
        self.updated_at_field = "updated_at"
        self._column_names = frozenset(inspect(model).columns.keys())

        required_fields = {id_field, *self.scope}
        if soft_delete_field is not None:
            required_fields.add(soft_delete_field)
        missing_fields = required_fields - self._column_names
        if missing_fields:
            missing = ", ".join(sorted(missing_fields))
            raise ValueError(f"{model.__name__} is missing configured CRUD fields: {missing}")
        if not mutable_fields <= self._column_names:
            invalid = ", ".join(sorted(mutable_fields - self._column_names))
            raise ValueError(f"Unknown mutable fields for {model.__name__}: {invalid}")

        protected_fields = {id_field, *self.scope}
        if soft_delete_field is not None:
            protected_fields.add(soft_delete_field)
        if mutable_fields & protected_fields:
            protected = ", ".join(sorted(mutable_fields & protected_fields))
            raise ValueError(f"Protected fields cannot be mutable: {protected}")
        self.mutable_fields = mutable_fields

    def _active_statement(self) -> Any:
        statement = select(self.model)
        for field, value in self.scope.items():
            statement = statement.where(getattr(self.model, field) == value)
        if self.soft_delete_field is not None:
            statement = statement.where(getattr(self.model, self.soft_delete_field).is_(None))
        return statement

    def _data_from(self, data: BaseModel | Mapping[str, Any], *, partial: bool) -> dict[str, Any]:
        if isinstance(data, BaseModel):
            values = data.model_dump(exclude_unset=partial)
        else:
            values = dict(data)
        unknown = set(values) - self._column_names
        if unknown:
            fields = ", ".join(sorted(unknown))
            raise ValueError(f"Unknown {self.model.__name__} fields: {fields}")
        return values

    @staticmethod
    def _validate_pagination(*, offset: int, limit: int) -> None:
        """Apply the common offset-page bounds used by every CRUD service."""

        if offset < 0:
            raise ValueError("offset must be non-negative")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

    async def _get_page[ItemT](
        self,
        statement: Any,
        *,
        offset: int,
        limit: int,
        item_type: type[ItemT],
    ) -> PageResult[ItemT]:
        """Fetch one sentinel row and derive an accurate next offset without a count query."""

        self._validate_pagination(offset=offset, limit=limit)
        result = await self.session.exec(statement.offset(offset).limit(limit + 1))
        items = cast(list[ItemT], result.all())
        has_more = len(items) > limit
        return PageResult(items=items[:limit], next_offset=offset + limit if has_more else None)

    def _assert_mutable_entity(self, entity: ModelT) -> None:
        for field, value in self.scope.items():
            if getattr(entity, field) != value:
                raise ValueError("Entity is outside this CRUD scope")
        if (
            self.soft_delete_field is not None
            and getattr(entity, self.soft_delete_field) is not None
        ):
            raise ValueError("Entity has already been deleted")

    async def get(self, entity_id: UUID) -> ModelT | None:
        """Get an active model by primary key within the configured scope."""

        id_column = getattr(self.model, self.id_field)
        result = await self.session.exec(self._active_statement().where(id_column == entity_id))
        return result.one_or_none()

    async def get_multi(self, *, offset: int = 0, limit: int = 100) -> Sequence[ModelT]:
        """List active scoped models using bounded offset pagination."""

        return (await self.get_page(offset=offset, limit=limit)).items

    async def get_page(self, *, offset: int = 0, limit: int = 100) -> PageResult[ModelT]:
        """List active scoped models with a precise continuation offset."""

        return await self._get_page(
            self._active_statement(),
            offset=offset,
            limit=limit,
            item_type=self.model,
        )

    async def create(self, data: CreateSchemaT | Mapping[str, Any]) -> ModelT:
        """Add and flush a scoped model without committing the transaction."""

        values = self._data_from(data, partial=False)
        protected_fields = {self.id_field, self.updated_at_field}
        if self.soft_delete_field is not None:
            protected_fields.add(self.soft_delete_field)
        supplied_protected = protected_fields & set(values)
        if supplied_protected:
            fields = ", ".join(sorted(supplied_protected))
            raise ValueError(f"Protected fields cannot be supplied when creating: {fields}")
        for field, value in self.scope.items():
            supplied_value = values.pop(field, value)
            if supplied_value != value:
                raise ValueError(f"{field} must match the configured CRUD scope")
        entity = self.model(**values, **self.scope)
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update(self, entity: ModelT, data: UpdateSchemaT | Mapping[str, Any]) -> ModelT:
        """Apply an allow-listed partial update and flush it without committing."""

        self._assert_mutable_entity(entity)
        values = self._data_from(data, partial=True)
        prohibited = set(values) - self.mutable_fields
        if prohibited:
            fields = ", ".join(sorted(prohibited))
            raise ValueError(f"Fields are not mutable for {self.model.__name__}: {fields}")
        for field, value in values.items():
            setattr(entity, field, value)
        if self.updated_at_field in self._column_names:
            setattr(entity, self.updated_at_field, utc_now())
        await self.session.flush()
        return entity

    async def delete(self, entity: ModelT) -> None:
        """Delete a scoped model, using soft deletion when configured."""

        self._assert_mutable_entity(entity)
        if self.soft_delete_field is None:
            await self.session.delete(entity)
        else:
            setattr(entity, self.soft_delete_field, utc_now())
            if self.updated_at_field in self._column_names:
                setattr(entity, self.updated_at_field, utc_now())
        await self.session.flush()
