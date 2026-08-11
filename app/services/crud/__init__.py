"""Table-specific CRUD operations used by application services."""

from app.services.crud.conversations import ConversationCRUD
from app.services.crud.messages import MessageCRUD

__all__ = ["ConversationCRUD", "MessageCRUD"]
