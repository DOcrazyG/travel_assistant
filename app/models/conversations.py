# pyright: reportAssignmentType=false
"""Conversation resource and LangGraph thread mapping."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Column, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.models.base import APP_SCHEMA, TimestampedModel, new_uuid7, utc_datetime_field


class Conversation(TimestampedModel, table=True):
    """The public conversation resource and internal LangGraph thread mapping."""

    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived', 'deleted')",
            name="ck_conversations_status",
        ),
        CheckConstraint("latest_message_sequence >= 0", name="ck_conversations_latest_sequence"),
        CheckConstraint("version > 0", name="ck_conversations_version"),
        CheckConstraint(
            "title_source IS NULL OR title_source IN ('system', 'user')",
            name="ck_conversations_title_source",
        ),
        CheckConstraint(
            "(status = 'deleted') = (deleted_at IS NOT NULL)",
            name="ck_conversations_deleted_lifecycle",
        ),
        Index(
            "ix_conversations_user_history",
            "user_id",
            "last_message_at",
            "id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_conversations_status_history",
            "status",
            "last_message_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_conversations_purge_after",
            "purge_after_at",
            postgresql_where=text("deleted_at IS NOT NULL"),
        ),
        {"schema": APP_SCHEMA},
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    user_id: UUID = Field(foreign_key=f"{APP_SCHEMA}.users.id")
    thread_id: UUID = Field(default_factory=new_uuid7, unique=True)
    title: str | None = Field(default=None, max_length=500)
    title_source: str | None = Field(default=None, max_length=16)
    status: str = Field(default="active", max_length=16)
    metadata_: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )
    last_message_at: datetime | None = utc_datetime_field(default=None)
    latest_message_sequence: int = Field(default=0)
    version: int = Field(default=1)
    archived_at: datetime | None = utc_datetime_field(default=None)
    deleted_at: datetime | None = utc_datetime_field(default=None)
    purge_after_at: datetime | None = utc_datetime_field(default=None)
