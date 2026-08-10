# pyright: reportAssignmentType=false
"""Confirmed, user-managed long-term travel preferences."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Column, ForeignKeyConstraint, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.models.base import APP_SCHEMA, TimestampedModel, new_uuid7, utc_datetime_field


class TravelPreference(TimestampedModel, table=True):
    """A user-confirmed long-term preference, introduced with P4 features."""

    __tablename__ = "travel_preferences"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_principal_id", "tenant_id"],
            [f"{APP_SCHEMA}.users.principal_id", f"{APP_SCHEMA}.users.tenant_id"],
            name="fk_travel_preferences_user_tenant",
        ),
        ForeignKeyConstraint(
            ["source_message_id", "tenant_id"],
            [f"{APP_SCHEMA}.messages.id", f"{APP_SCHEMA}.messages.tenant_id"],
            name="fk_travel_preferences_source_message_tenant",
        ),
        CheckConstraint(
            "status IN ('confirmed', 'revoked', 'expired')",
            name="ck_travel_preferences_status",
        ),
        Index(
            "uq_travel_preferences_confirmed_category",
            "user_principal_id",
            "category",
            unique=True,
            postgresql_where=text("status = 'confirmed' AND deleted_at IS NULL"),
        ),
        Index(
            "ix_travel_preferences_user_status",
            "tenant_id",
            "user_principal_id",
            "status",
        ),
        Index(
            "ix_travel_preferences_expiry",
            "expires_at",
            postgresql_where=text("status = 'confirmed'"),
        ),
        {"schema": APP_SCHEMA},
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    tenant_id: UUID = Field(index=True)
    user_principal_id: UUID = Field(index=True)
    category: str = Field(max_length=64)
    value: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    source_message_id: UUID | None = Field(default=None, index=True)
    status: str = Field(default="confirmed", max_length=16)
    confirmed_at: datetime | None = utc_datetime_field(default=None)
    expires_at: datetime | None = utc_datetime_field(default=None)
    deleted_at: datetime | None = utc_datetime_field(default=None)
