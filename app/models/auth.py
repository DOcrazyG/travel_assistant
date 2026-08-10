# pyright: reportAssignmentType=false
"""Local-account sessions, refresh tokens, revocations, and one-time tokens."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    text,
)
from sqlmodel import Field, SQLModel

from app.models.base import APP_SCHEMA, new_uuid7, utc_datetime_field, utc_now


class AuthSession(SQLModel, table=True):
    """A revocable refresh-token family for one local account and device."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_principal_id", "tenant_id"],
            [f"{APP_SCHEMA}.users.principal_id", f"{APP_SCHEMA}.users.tenant_id"],
            name="fk_auth_sessions_user_tenant",
        ),
        Index(
            "ix_auth_sessions_active_user_expiry",
            "user_principal_id",
            "expires_at",
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index("ix_auth_sessions_expiry", "expires_at"),
        {"schema": APP_SCHEMA},
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    tenant_id: UUID = Field(index=True)
    user_principal_id: UUID = Field(index=True)
    token_family_id: UUID = Field(default_factory=new_uuid7, unique=True)
    created_at: datetime = utc_datetime_field(default_factory=utc_now)
    last_used_at: datetime | None = utc_datetime_field(default=None)
    expires_at: datetime = utc_datetime_field()
    revoked_at: datetime | None = utc_datetime_field(default=None)
    revoked_reason: str | None = Field(default=None, max_length=100)
    user_agent: str | None = Field(default=None, max_length=512)
    ip_hash: bytes | None = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )


class RefreshToken(SQLModel, table=True):
    """A hashed refresh token created for every session-token rotation."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_refresh_tokens_session_issued", "session_id", "issued_at"),
        Index("ix_refresh_tokens_expiry", "expires_at"),
        {"schema": APP_SCHEMA},
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    session_id: UUID = Field(foreign_key=f"{APP_SCHEMA}.auth_sessions.id", index=True)
    token_hash: bytes = Field(
        sa_column=Column(LargeBinary, nullable=False, unique=True)
    )
    issued_at: datetime = utc_datetime_field(default_factory=utc_now)
    expires_at: datetime = utc_datetime_field()
    consumed_at: datetime | None = utc_datetime_field(default=None)
    revoked_at: datetime | None = utc_datetime_field(default=None)
    replaced_by_id: UUID | None = Field(
        default=None, foreign_key=f"{APP_SCHEMA}.refresh_tokens.id"
    )


class RevokedAccessToken(SQLModel, table=True):
    """JWT IDs revoked before their naturally short access-token expiry."""

    __tablename__ = "revoked_access_tokens"
    __table_args__ = (
        Index("ix_revoked_access_tokens_expiry", "expires_at"),
        {"schema": APP_SCHEMA},
    )

    jti: UUID = Field(primary_key=True)
    user_principal_id: UUID = Field(
        foreign_key=f"{APP_SCHEMA}.users.principal_id", index=True
    )
    expires_at: datetime = utc_datetime_field()
    revoked_at: datetime = utc_datetime_field(default_factory=utc_now)
    reason: str = Field(max_length=100)


class AuthOneTimeToken(SQLModel, table=True):
    """A hashed, expiring email-verification or password-reset token."""

    __tablename__ = "auth_one_time_tokens"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('email_verify', 'password_reset')",
            name="ck_auth_one_time_tokens_purpose",
        ),
        Index(
            "ix_auth_one_time_tokens_user_purpose_created",
            "user_principal_id",
            "purpose",
            "created_at",
        ),
        Index("ix_auth_one_time_tokens_expiry", "expires_at"),
        {"schema": APP_SCHEMA},
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    user_principal_id: UUID = Field(
        foreign_key=f"{APP_SCHEMA}.users.principal_id", index=True
    )
    purpose: str = Field(max_length=32)
    token_hash: bytes = Field(
        sa_column=Column(LargeBinary, nullable=False, unique=True)
    )
    expires_at: datetime = utc_datetime_field()
    consumed_at: datetime | None = utc_datetime_field(default=None)
    created_at: datetime = utc_datetime_field(default_factory=utc_now)
    request_ip_hash: bytes | None = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )
    request_user_agent: str | None = Field(default=None, max_length=512)
