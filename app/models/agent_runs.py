# pyright: reportAssignmentType=false
"""Agent execution lifecycle and controlled-tool audit tables."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Column, Index, Numeric, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import (
    APP_SCHEMA,
    TimestampedModel,
    new_uuid7,
    utc_datetime_field,
    utc_now,
)


class AgentRun(TimestampedModel, table=True):
    """A durable lifecycle record for one accepted Agent invocation."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'interrupted', 'completed', 'failed', 'cancelled')",
            name="ck_agent_runs_status",
        ),
        Index(
            "uq_agent_runs_active_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running', 'interrupted')"),
        ),
        Index("ix_agent_runs_conversation_created", "conversation_id", "created_at"),
        Index("ix_agent_runs_status_created", "status", "created_at"),
        Index(
            "ix_agent_runs_terminal_completed",
            "completed_at",
            postgresql_where=text("status IN ('completed', 'failed', 'cancelled')"),
        ),
        {"schema": APP_SCHEMA},
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    conversation_id: UUID = Field(foreign_key=f"{APP_SCHEMA}.conversations.id")
    status: str = Field(default="queued", max_length=16)
    model_alias: str | None = Field(default=None, max_length=200)
    provider_model: str | None = Field(default=None, max_length=200)
    request_metadata: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )
    trace_id: str | None = Field(default=None, max_length=255)
    input_tokens: int | None = Field(default=None)
    output_tokens: int | None = Field(default=None)
    total_tokens: int | None = Field(default=None)
    estimated_cost: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(12, 6), nullable=True)
    )
    started_at: datetime | None = utc_datetime_field(default=None)
    completed_at: datetime | None = utc_datetime_field(default=None)
    error_code: str | None = Field(default=None, max_length=100)
    error_details: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    interrupt_payload: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )


class ToolCall(SQLModel, table=True):
    """A redacted audit record for one controlled tool call within an Agent run."""

    __tablename__ = "tool_calls"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'timed_out', 'cancelled')",
            name="ck_tool_calls_status",
        ),
        CheckConstraint("sequence > 0", name="ck_tool_calls_sequence"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="ck_tool_calls_duration"),
        Index("uq_tool_calls_run_sequence", "agent_run_id", "sequence", unique=True),
        Index("ix_tool_calls_name_created", "tool_name", "created_at"),
        Index(
            "ix_tool_calls_active",
            "status",
            "created_at",
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        {"schema": APP_SCHEMA},
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    agent_run_id: UUID = Field(foreign_key=f"{APP_SCHEMA}.agent_runs.id")
    sequence: int = Field()
    tool_name: str = Field(max_length=200)
    provider_call_id: str | None = Field(default=None, max_length=255)
    status: str = Field(default="queued", max_length=16)
    input_redacted: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )
    output_summary: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )
    source_urls: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    )
    started_at: datetime | None = utc_datetime_field(default=None)
    completed_at: datetime | None = utc_datetime_field(default=None)
    duration_ms: int | None = Field(default=None)
    error_code: str | None = Field(default=None, max_length=100)
    error_details: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    created_at: datetime = utc_datetime_field(default_factory=utc_now)
