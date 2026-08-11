"""CRUD operations specific to conversation records."""

from uuid import UUID

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.crud import SQLModelCRUD
from app.models.conversations import Conversation


class ConversationCRUD(SQLModelCRUD[Conversation, BaseModel, BaseModel]):
    """Scoped CRUD for one user's soft-deletable conversations."""

    def __init__(self, session: AsyncSession, user_id: UUID) -> None:
        super().__init__(
            Conversation,
            session,
            scope={"user_id": user_id},
            mutable_fields=frozenset({"title", "title_source"}),
            soft_delete_field="deleted_at",
        )
