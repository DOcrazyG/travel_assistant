"""Scoped CRUD operations for canonical messages in one authorized conversation."""

from typing import Any
from uuid import UUID

from sqlalchemy import inspect
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.crud import SQLModelCRUD
from app.models.messages import Message
from app.schemas.messages import MessageCreate, MessageUpdate


def _column(model: type[SQLModel], name: str) -> Any:
    """Access mapped SQL columns while keeping SQL details inside the CRUD layer."""

    return inspect(model).columns[name]


class MessageCRUD(SQLModelCRUD[Message, MessageCreate, MessageUpdate]):
    """Persist and page messages that belong to exactly one verified conversation."""

    def __init__(self, session: AsyncSession, conversation_id: UUID) -> None:
        super().__init__(
            Message,
            session,
            scope={"conversation_id": conversation_id},
            mutable_fields=frozenset({"content", "rendered_text", "content_status", "token_count"}),
            soft_delete_field="deleted_at",
        )

    def _active_statement(self) -> Any:
        """Keep the canonical transcript in ascending per-conversation sequence order."""

        return super()._active_statement().order_by(_column(Message, "sequence"))
