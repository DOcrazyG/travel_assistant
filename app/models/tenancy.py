# pyright: reportAssignmentType=false
"""Tenant ownership subjects and memberships."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, UniqueConstraint, text
from sqlmodel import Field

from app.models.base import APP_SCHEMA, TimestampedModel, new_uuid7, utc_datetime_field


class Tenant(TimestampedModel, table=True):
    """A personal workspace now and a team workspace in a later release."""

    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("kind IN ('personal', 'team')", name="ck_tenants_kind"),
        CheckConstraint(
            "status IN ('active', 'suspended', 'deleted')", name="ck_tenants_status"
        ),
        Index(
            "ix_tenants_active_status",
            "status",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": APP_SCHEMA},
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    kind: str = Field(default="personal", max_length=16)
    name: str = Field(max_length=200)
    status: str = Field(default="active", max_length=16)
    deleted_at: datetime | None = utc_datetime_field(default=None)


class Principal(TimestampedModel, table=True):
    """The only ownership subject for tenant data: a user or a service."""

    __tablename__ = "principals"
    __table_args__ = (
        CheckConstraint("kind IN ('user', 'service')", name="ck_principals_kind"),
        CheckConstraint(
            "status IN ('active', 'suspended', 'deleted')", name="ck_principals_status"
        ),
        UniqueConstraint("id", "tenant_id", name="uq_principals_id_tenant"),
        Index(
            "ix_principals_tenant_active",
            "tenant_id",
            "status",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": APP_SCHEMA},
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    tenant_id: UUID = Field(foreign_key=f"{APP_SCHEMA}.tenants.id", index=True)
    kind: str = Field(max_length=16)
    status: str = Field(default="active", max_length=16)
    display_name: str = Field(max_length=200)
    deleted_at: datetime | None = utc_datetime_field(default=None)


class TenantMembership(TimestampedModel, table=True):
    """A user's role in a tenant; personal tenants have a single owner initially."""

    __tablename__ = "tenant_memberships"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin', 'member')", name="ck_memberships_role"
        ),
        CheckConstraint(
            "status IN ('active', 'invited', 'removed')", name="ck_memberships_status"
        ),
        Index("ix_memberships_user_status", "user_principal_id", "status"),
        {"schema": APP_SCHEMA},
    )

    tenant_id: UUID = Field(foreign_key=f"{APP_SCHEMA}.tenants.id", primary_key=True)
    user_principal_id: UUID = Field(
        foreign_key=f"{APP_SCHEMA}.users.principal_id", primary_key=True
    )
    role: str = Field(default="owner", max_length=16)
    status: str = Field(default="active", max_length=16)
    removed_at: datetime | None = utc_datetime_field(default=None)
