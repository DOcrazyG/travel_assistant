# pyright: reportAssignmentType=false
"""Local password-account table."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Column, Index, Text, text
from sqlmodel import Field

from app.models.base import APP_SCHEMA, TimestampedModel, new_uuid7, utc_datetime_field


class User(TimestampedModel, table=True):
    """A local password account authenticated by its normalized email address."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_verification', 'active', 'disabled', 'deleted')",
            name="ck_users_status",
        ),
        CheckConstraint(
            "email_normalized = lower(email_normalized)",
            name="ck_users_email_normalized",
        ),
        CheckConstraint(
            "(status = 'deleted') = (deleted_at IS NOT NULL)",
            name="ck_users_deleted_lifecycle",
        ),
        Index(
            "uq_users_active_email_normalized",
            "email_normalized",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_users_active_status",
            "status",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_users_single_admin",
            text("(true)"),
            unique=True,
            postgresql_where=text("is_admin IS TRUE AND deleted_at IS NULL"),
        ),
        {"schema": APP_SCHEMA},
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    email: str = Field(max_length=320)
    email_normalized: str = Field(max_length=320)
    password_hash: str = Field(sa_column=Column(Text, nullable=False))
    status: str = Field(default="active", max_length=32)
    is_admin: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    email_verified_at: datetime | None = utc_datetime_field(default=None)
    password_changed_at: datetime | None = utc_datetime_field(default=None)
    security_invalid_before: datetime | None = utc_datetime_field(default=None)
    last_login_at: datetime | None = utc_datetime_field(default=None)
    deleted_at: datetime | None = utc_datetime_field(default=None)
