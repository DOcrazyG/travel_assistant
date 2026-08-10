# pyright: reportAssignmentType=false
"""Service principals and their separately managed API keys."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Column,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
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


class ServicePrincipal(TimestampedModel, table=True):
    """A machine principal that owns its own API-key conversations."""

    __tablename__ = "service_principals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["principal_id", "tenant_id"],
            [f"{APP_SCHEMA}.principals.id", f"{APP_SCHEMA}.principals.tenant_id"],
            name="fk_service_principals_principal_tenant",
        ),
        UniqueConstraint(
            "principal_id", "tenant_id", name="uq_service_principals_principal_tenant"
        ),
        {"schema": APP_SCHEMA},
    )

    principal_id: UUID = Field(primary_key=True)
    tenant_id: UUID = Field(index=True)
    name: str = Field(max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    created_by_user_principal_id: UUID = Field(
        foreign_key=f"{APP_SCHEMA}.users.principal_id", index=True
    )


class ApiKey(SQLModel, table=True):
    """A separately revocable, hashed credential for a service principal."""

    __tablename__ = "api_keys"
    __table_args__ = (
        ForeignKeyConstraint(
            ["service_principal_id", "tenant_id"],
            [
                f"{APP_SCHEMA}.service_principals.principal_id",
                f"{APP_SCHEMA}.service_principals.tenant_id",
            ],
            name="fk_api_keys_service_principal_tenant",
        ),
        Index("ix_api_keys_prefix", "key_prefix"),
        Index(
            "ix_api_keys_active_service_expiry",
            "service_principal_id",
            "expires_at",
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index("ix_api_keys_expiry", "expires_at"),
        {"schema": APP_SCHEMA},
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    tenant_id: UUID = Field(index=True)
    service_principal_id: UUID = Field(index=True)
    name: str = Field(max_length=200)
    key_prefix: str = Field(max_length=32)
    secret_hash: bytes = Field(sa_column=Column(LargeBinary, nullable=False, unique=True))
    scopes: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    )
    created_at: datetime = utc_datetime_field(default_factory=utc_now)
    last_used_at: datetime | None = utc_datetime_field(default=None)
    expires_at: datetime | None = utc_datetime_field(default=None)
    revoked_at: datetime | None = utc_datetime_field(default=None)
    created_by_user_principal_id: UUID = Field(
        foreign_key=f"{APP_SCHEMA}.users.principal_id", index=True
    )
