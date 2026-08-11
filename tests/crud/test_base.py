"""Tests for TenantCRUD policy guarantees."""

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy.dialects import postgresql

from app.core.crud.base import SQLModelCRUD
from app.models.conversations import Conversation


class ConversationCreate(BaseModel):
    user_id: UUID
    title: str | None = None


class ConversationUpdate(BaseModel):
    title: str | None = None
    status: str | None = None


class FakeResult:
    def __init__(self, entity: Conversation | None = None) -> None:
        self.entity = entity

    def one_or_none(self) -> Conversation | None:
        return self.entity

    def scalar_one_or_none(self) -> Conversation | None:
        return self.entity

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> list[Conversation]:
        return [self.entity] if self.entity else []


class FakeSession:
    def __init__(self, result: FakeResult | None = None) -> None:
        self.result = result or FakeResult()
        self.statements: list[Any] = []
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.flush_count = 0

    async def exec(self, statement: Any) -> FakeResult:
        self.statements.append(statement)
        return self.result

    def add(self, entity: Any) -> None:
        self.added.append(entity)

    async def delete(self, entity: Any) -> None:
        self.deleted.append(entity)

    async def flush(self) -> None:
        self.flush_count += 1


def crud_for(
    session: FakeSession, user_id: UUID
) -> SQLModelCRUD[Conversation, ConversationCreate, ConversationUpdate]:
    return SQLModelCRUD(
        Conversation,
        session,  # type: ignore[arg-type]
        scope={"user_id": user_id},
        mutable_fields=frozenset({"title", "status"}),
        soft_delete_field="deleted_at",
    )


def test_get_always_scopes_to_user_and_hides_soft_deleted_records() -> None:
    user_id = uuid4()
    session = FakeSession()
    crud = crud_for(session, user_id)

    asyncio.run(crud.get(uuid4()))

    compiled = session.statements[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "app.conversations.user_id =" in sql
    assert "app.conversations.deleted_at IS NULL" in sql
    assert user_id in compiled.params.values()


def test_get_page_uses_a_sentinel_row_for_an_accurate_next_offset() -> None:
    user_id = uuid4()
    first = Conversation(user_id=user_id)
    second = Conversation(user_id=user_id)
    third = Conversation(user_id=user_id)
    session = FakeSession()
    session.result = FakeResult()
    session.result.all = lambda: [first, second, third]  # type: ignore[method-assign]
    crud = crud_for(session, user_id)

    page = asyncio.run(crud.get_page(offset=4, limit=2))

    assert page.items == [first, second]
    assert page.next_offset == 6
    compiled = session.statements[0].compile(dialect=postgresql.dialect())
    assert 3 in compiled.params.values()


def test_create_sets_scope_and_only_flushes() -> None:
    user_id = uuid4()
    session = FakeSession()
    crud = crud_for(session, user_id)

    entity = asyncio.run(crud.create(ConversationCreate(user_id=user_id, title="Lisbon")))

    assert entity.user_id == user_id
    assert session.added == [entity]
    assert session.flush_count == 1


def test_create_rejects_cross_scope_input() -> None:
    crud = crud_for(FakeSession(), uuid4())

    with pytest.raises(ValueError, match="user_id must match"):
        asyncio.run(crud.create({"user_id": uuid4()}))


def test_update_only_allows_declared_fields() -> None:
    user_id = uuid4()
    entity = Conversation(user_id=user_id, title="Old")
    session = FakeSession()
    crud = crud_for(session, user_id)

    updated = asyncio.run(crud.update(entity, ConversationUpdate(title="New")))

    assert updated.title == "New"
    assert session.flush_count == 1

    with pytest.raises(ValueError, match="not mutable"):
        asyncio.run(crud.update(entity, {"user_id": uuid4()}))


def test_delete_uses_soft_delete_when_configured() -> None:
    user_id = uuid4()
    entity = Conversation(user_id=user_id, title="Old")
    session = FakeSession()
    crud = crud_for(session, user_id)

    asyncio.run(crud.delete(entity))

    assert entity.deleted_at is not None
    assert session.deleted == []
    assert session.flush_count == 1
