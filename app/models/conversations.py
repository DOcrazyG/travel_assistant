# pyright: reportAssignmentType=false
"""Conversation resource and LangGraph thread mapping."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.models.base import APP_SCHEMA, TimestampedModel, new_uuid7, utc_datetime_field


class Conversation(TimestampedModel, table=True):
    """The public conversation resource and internal LangGraph thread mapping."""

    __tablename__ = "conversations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_principal_id", "tenant_id"],
            [f"{APP_SCHEMA}.principals.id", f"{APP_SCHEMA}.principals.tenant_id"],
            name="fk_conversations_owner_principal_tenant",
        ),
        CheckConstraint(
            "status IN ('active', 'archived', 'deleted')",
            name="ck_conversations_status",
        ),
        CheckConstraint(
            "latest_message_sequence >= 0", name="ck_conversations_latest_sequence"
        ),
        CheckConstraint("version > 0", name="ck_conversations_version"),
        UniqueConstraint("id", "tenant_id", name="uq_conversations_id_tenant"),
        Index(
            "ix_conversations_owner_history",
            "tenant_id",
            "owner_principal_id",
            "last_message_at",
            "id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_conversations_status_history",
            "tenant_id",
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
    tenant_id: UUID = Field(index=True)
    owner_principal_id: UUID = Field(index=True)
    thread_id: UUID = Field(default_factory=new_uuid7, unique=True)
    title: str | None = Field(default=None, max_length=500)
    title_source: str | None = Field(default=None, max_length=16)
    status: str = Field(default="active", max_length=16)
    metadata_: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(
            "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
        ),
    )
    last_message_at: datetime | None = utc_datetime_field(default=None)
    latest_message_sequence: int = Field(default=0)
    version: int = Field(default=1)
    archived_at: datetime | None = utc_datetime_field(default=None)
    deleted_at: datetime | None = utc_datetime_field(default=None)
    purge_after_at: datetime | None = utc_datetime_field(default=None)
    deleted_by_principal_id: UUID | None = Field(
        default=None, foreign_key=f"{APP_SCHEMA}.principals.id"
    )
