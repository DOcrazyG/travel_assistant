"""Application-owned SQLModel tables.

Importing this module registers all application tables in ``SQLModel.metadata`` for
Alembic. LangGraph checkpoint tables deliberately remain dependency-owned.
"""

from app.models.agent_runs import AgentRun, ToolCall
from app.models.attachments import Attachment, MessageAttachment
from app.models.auth import (
    AuthOneTimeToken,
    AuthSession,
    RefreshToken,
    RevokedAccessToken,
)
from app.models.conversations import Conversation
from app.models.messages import Message, MessageCitation
from app.models.operations import (
    DataDeletionRequest,
    IdempotencyKey,
    SecurityAuditEvent,
)
from app.models.preferences import TravelPreference
from app.models.users import User

__all__ = [
    "AgentRun",
    "Attachment",
    "AuthOneTimeToken",
    "AuthSession",
    "Conversation",
    "DataDeletionRequest",
    "IdempotencyKey",
    "Message",
    "MessageAttachment",
    "MessageCitation",
    "RefreshToken",
    "RevokedAccessToken",
    "SecurityAuditEvent",
    "ToolCall",
    "TravelPreference",
    "User",
]
