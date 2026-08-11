# pyright: reportAssignmentType=false
"""Idempotency, security audit, and durable data-deletion operations."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Column, Index, LargeBinary, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import APP_SCHEMA, new_uuid7, utc_datetime_field, utc_now


class IdempotencyKey(SQLModel, table=True):
    """A request fingerprint that prevents duplicate chat execution."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name="ck_idempotency_keys_status",
        ),
        Index(
            "uq_idempotency_keys_request",
            "http_method",
            "route",
            "idempotency_key",
            unique=True,
        ),
        Index("ix_idempotency_keys_expiry", "expires_at"),
        Index(
            "ix_idempotency_keys_conversation",
            "conversation_id",
            postgresql_where=text("conversation_id IS NOT NULL"),
        ),
        {"schema": APP_SCHEMA},
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    http_method: str = Field(max_length=10)
    route: str = Field(max_length=255)
    idempotency_key: str = Field(max_length=255)
    request_fingerprint: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    conversation_id: UUID | None = Field(
        default=None, foreign_key=f"{APP_SCHEMA}.conversations.id"
    )
    agent_run_id: UUID | None = Field(
        default=None, foreign_key=f"{APP_SCHEMA}.agent_runs.id"
    )
    status: str = Field(default="processing", max_length=16)
    response_status: int | None = Field(default=None)
    response_snapshot: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    created_at: datetime = utc_datetime_field(default_factory=utc_now)
    completed_at: datetime | None = utc_datetime_field(default=None)
    expires_at: datetime = utc_datetime_field()


class SecurityAuditEvent(SQLModel, table=True):
    """Append-only security and destructive-action audit events."""

    __tablename__ = "security_audit_events"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('success', 'failure', 'denied')",
            name="ck_security_audit_events_outcome",
        ),
        Index(
            "ix_security_audit_events_user_occurred",
            "user_id",
            "occurred_at",
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index("ix_security_audit_events_type_occurred", "event_type", "occurred_at"),
        Index("ix_security_audit_events_occurred", "occurred_at"),
        {"schema": APP_SCHEMA},
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: UUID | None = Field(default=None, foreign_key=f"{APP_SCHEMA}.users.id")
    event_type: str = Field(max_length=100)
    outcome: str = Field(max_length=16)
    request_id: UUID | None = Field(default=None, index=True)
    ip_hash: bytes | None = Field(default=None, sa_column=Column(LargeBinary, nullable=True))
    user_agent: str | None = Field(default=None, max_length=512)
    details: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )
    occurred_at: datetime = utc_datetime_field(default_factory=utc_now)


class DataDeletionRequest(SQLModel, table=True):
    """A durable, retryable record for explicit and retention-driven data purge."""

    __tablename__ = "data_deletion_requests"
    __table_args__ = (
        CheckConstraint(
            "target_type IN ('conversation', 'user', 'attachment')",
            name="ck_data_deletion_requests_target_type",
        ),
        CheckConstraint(
            "reason IN ('user_request', 'retention', 'admin')",
            name="ck_data_deletion_requests_reason",
        ),
        CheckConstraint(
            "status IN ('scheduled', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_data_deletion_requests_status",
        ),
        Index("ix_data_deletion_requests_due", "status", "purge_after_at"),
        Index("ix_data_deletion_requests_target", "target_type", "target_id"),
        Index("ix_data_deletion_requests_completed", "completed_at"),
        {"schema": APP_SCHEMA},
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    requested_by_user_id: UUID | None = Field(
        default=None, foreign_key=f"{APP_SCHEMA}.users.id"
    )
    target_type: str = Field(max_length=16)
    target_id: UUID = Field()
    reason: str = Field(max_length=16)
    status: str = Field(default="scheduled", max_length=16)
    requested_at: datetime = utc_datetime_field(default_factory=utc_now)
    purge_after_at: datetime = utc_datetime_field()
    started_at: datetime | None = utc_datetime_field(default=None)
    completed_at: datetime | None = utc_datetime_field(default=None)
    failure_code: str | None = Field(default=None, max_length=100)
    failure_detail: str | None = Field(default=None, max_length=1000)
    created_at: datetime = utc_datetime_field(default_factory=utc_now)
