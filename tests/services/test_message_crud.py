"""Unit tests for the independent, conversation-scoped message CRUD service."""

import asyncio
from typing import Any
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.models.messages import Message
from app.services.crud.messages import MessageCRUD


class FakeResult:
    def all(self) -> list[Message]:
        return []


class FakeSession:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def exec(self, statement: Any) -> FakeResult:
        self.statements.append(statement)
        return FakeResult()


def test_message_crud_scopes_history_to_one_conversation_and_orders_by_sequence() -> None:
    conversation_id = uuid4()
    session = FakeSession()
    crud = MessageCRUD(session, conversation_id)  # type: ignore[arg-type]

    page = asyncio.run(crud.get_page(offset=0, limit=20))

    compiled = session.statements[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "app.messages.conversation_id =" in sql
    assert "app.messages.deleted_at IS NULL" in sql
    assert "ORDER BY app.messages.sequence" in sql
    assert conversation_id in compiled.params.values()
    assert page.items == []
    assert page.next_offset is None
