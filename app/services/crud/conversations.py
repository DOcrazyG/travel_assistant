"""Scoped CRUD operations for conversation records and their message history."""

from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import inspect
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.crud import SQLModelCRUD
from app.core.errors import APIError
from app.models.base import utc_now
from app.models.conversations import Conversation
from app.models.operations import DataDeletionRequest
from app.schemas.conversations import ConversationCreate, ConversationUpdate


def _column(model: type[SQLModel], name: str) -> Any:
    """Access mapped SQL columns without exposing SQL in the route layer."""

    return inspect(model).columns[name]


class ConversationCRUD(SQLModelCRUD[Conversation, ConversationCreate, ConversationUpdate]):
    """The sole persistence boundary for one user's conversations.

    It retains the base CRUD contract while adapting creation, history ordering,
    and deletion scheduling to the conversation aggregate.
    """

    def __init__(self, session: AsyncSession, user_id: UUID) -> None:
        super().__init__(
            Conversation,
            session,
            scope={"user_id": user_id},
            mutable_fields=frozenset({"title", "title_source"}),
            soft_delete_field="deleted_at",
        )

    async def create(self, data: ConversationCreate) -> Conversation:
        """Create a caller-owned conversation and commit its server-generated IDs."""

        conversation = Conversation(
            user_id=self.scope["user_id"],
            title=data.title,
            title_source="user" if data.title is not None else None,
            metadata_=data.metadata,
        )
        self.session.add(conversation)
        await self.session.flush()
        await self.session.commit()
        await self.session.refresh(conversation)
        return conversation

    def _active_statement(self) -> Any:
        """Apply the conversation-specific most-recent-first ordering to base reads."""

        return super()._active_statement().order_by(
            _column(Conversation, "last_message_at").desc().nullslast(),
            _column(Conversation, "id").desc(),
        )

    async def require(self, conversation_id: UUID) -> Conversation:
        """Resolve an owned conversation or hide its existence with a shared 404."""

        conversation = await self.get(conversation_id)
        if conversation is None:
            raise APIError(404, "conversation_not_found", "Conversation was not found.")
        return conversation

    async def delete(self, entity: Conversation) -> None:
        """Soft-delete the aggregate and enqueue its retention-compliant physical purge."""

        self._assert_mutable_entity(entity)
        now = utc_now()
        purge_after_at = now + timedelta(days=30)
        entity.status = "deleted"
        entity.deleted_at = now
        entity.purge_after_at = purge_after_at
        entity.updated_at = now
        self.session.add(
            DataDeletionRequest(
                requested_by_user_id=self.scope["user_id"],
                target_type="conversation",
                target_id=entity.id,
                reason="user_request",
                purge_after_at=purge_after_at,
            )
        )
        await self.session.flush()
        await self.session.commit()
