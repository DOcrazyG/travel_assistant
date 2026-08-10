# pyright: reportAssignmentType=false
"""Canonical message history and rendered source citations."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import (
    APP_SCHEMA,
    TimestampedModel,
    new_uuid7,
    utc_datetime_field,
    utc_now,
)


class Message(TimestampedModel, table=True):
    """The canonical linear transcript used for frontend history rendering."""

    __tablename__ = "messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "tenant_id"],
            [f"{APP_SCHEMA}.conversations.id", f"{APP_SCHEMA}.conversations.tenant_id"],
            name="fk_messages_conversation_tenant",
        ),
        ForeignKeyConstraint(
            ["agent_run_id", "tenant_id"],
            [f"{APP_SCHEMA}.agent_runs.id", f"{APP_SCHEMA}.agent_runs.tenant_id"],
            name="fk_messages_agent_run_tenant",
        ),
        CheckConstraint("role IN ('user', 'assistant', 'system', 'tool')", name="ck_messages_role"),
        CheckConstraint(
            "content_status IN ('complete', 'partial', 'failed', 'redacted')",
            name="ck_messages_content_status",
        ),
        CheckConstraint("sequence > 0", name="ck_messages_sequence"),
        CheckConstraint("jsonb_typeof(content) = 'array'", name="ck_messages_content_array"),
        UniqueConstraint("id", "tenant_id", name="uq_messages_id_tenant"),
        UniqueConstraint("conversation_id", "sequence", name="uq_messages_conversation_sequence"),
        Index(
            "ix_messages_conversation_history",
            "conversation_id",
            "sequence",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_messages_agent_run",
            "agent_run_id",
            postgresql_where=text("agent_run_id IS NOT NULL"),
        ),
        {"schema": APP_SCHEMA},
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    tenant_id: UUID = Field(index=True)
    conversation_id: UUID = Field(index=True)
    sequence: int = Field()
    role: str = Field(max_length=16)
    content: list[dict[str, Any]] = Field(sa_column=Column(JSONB, nullable=False))
    rendered_text: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    content_status: str = Field(default="complete", max_length=16)
    agent_run_id: UUID | None = Field(default=None, index=True)
    model_alias: str | None = Field(default=None, max_length=200)
    token_count: int | None = Field(default=None)
    deleted_at: datetime | None = utc_datetime_field(default=None)


class MessageCitation(SQLModel, table=True):
    """A sanitized source reference rendered with a historical assistant response."""

    __tablename__ = "message_citations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["message_id", "tenant_id"],
            [f"{APP_SCHEMA}.messages.id", f"{APP_SCHEMA}.messages.tenant_id"],
            name="fk_message_citations_message_tenant",
        ),
        CheckConstraint("position >= 0", name="ck_message_citations_position"),
        Index("uq_message_citations_position", "message_id", "position", unique=True),
        {"schema": APP_SCHEMA},
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    tenant_id: UUID = Field(index=True)
    message_id: UUID = Field(index=True)
    position: int = Field()
    source_type: str = Field(max_length=64)
    provider: str | None = Field(default=None, max_length=100)
    title: str = Field(max_length=500)
    url: str = Field(max_length=2048)
    snippet: str | None = Field(default=None, max_length=2000)
    retrieved_at: datetime = utc_datetime_field()
    published_at: datetime | None = utc_datetime_field(default=None)
    created_at: datetime = utc_datetime_field(default_factory=utc_now)
