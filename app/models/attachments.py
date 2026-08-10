# pyright: reportAssignmentType=false
"""MinIO attachment metadata and message links."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    UniqueConstraint,
    text,
)
from sqlmodel import Field, SQLModel

from app.models.base import APP_SCHEMA, new_uuid7, utc_datetime_field, utc_now


class Attachment(SQLModel, table=True):
    """Metadata for a MinIO object; bytes never enter PostgreSQL."""

    __tablename__ = "attachments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["uploader_principal_id", "tenant_id"],
            [f"{APP_SCHEMA}.principals.id", f"{APP_SCHEMA}.principals.tenant_id"],
            name="fk_attachments_uploader_principal_tenant",
        ),
        CheckConstraint("kind IN ('image', 'file')", name="ck_attachments_kind"),
        CheckConstraint(
            "upload_status IN "
            "('pending_upload', 'uploaded', 'scanning', 'available', 'rejected', 'deleted')",
            name="ck_attachments_upload_status",
        ),
        CheckConstraint(
            "scan_status IN ('pending', 'clean', 'infected', 'failed')",
            name="ck_attachments_scan_status",
        ),
        CheckConstraint(
            "processing_status IN ('not_requested', 'queued', 'processed', 'failed')",
            name="ck_attachments_processing_status",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_attachments_id_tenant"),
        Index(
            "uq_attachments_object_location",
            "storage_provider",
            "bucket",
            "object_key",
            unique=True,
        ),
        Index(
            "ix_attachments_uploader_created",
            "tenant_id",
            "uploader_principal_id",
            "created_at",
        ),
        Index("ix_attachments_upload_expiry", "upload_status", "expires_at"),
        Index(
            "ix_attachments_scan_work",
            "scan_status",
            postgresql_where=text("scan_status IN ('pending', 'failed')"),
        ),
        {"schema": APP_SCHEMA},
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    tenant_id: UUID = Field(index=True)
    uploader_principal_id: UUID = Field(index=True)
    storage_provider: str = Field(default="minio", max_length=32)
    bucket: str = Field(max_length=255)
    object_key: str = Field(max_length=1024)
    original_filename: str = Field(max_length=512)
    media_type: str = Field(max_length=255)
    byte_size: int = Field()
    sha256: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    kind: str = Field(max_length=16)
    upload_status: str = Field(default="pending_upload", max_length=32)
    scan_status: str = Field(default="pending", max_length=16)
    scan_detail: str | None = Field(default=None, max_length=1000)
    processing_status: str = Field(default="not_requested", max_length=32)
    created_at: datetime = utc_datetime_field(default_factory=utc_now)
    uploaded_at: datetime | None = utc_datetime_field(default=None)
    expires_at: datetime | None = utc_datetime_field(default=None)
    deleted_at: datetime | None = utc_datetime_field(default=None)


class MessageAttachment(SQLModel, table=True):
    """A single-use, ordered attachment link for one message content part."""

    __tablename__ = "message_attachments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["message_id", "tenant_id"],
            [f"{APP_SCHEMA}.messages.id", f"{APP_SCHEMA}.messages.tenant_id"],
            name="fk_message_attachments_message_tenant",
        ),
        ForeignKeyConstraint(
            ["attachment_id", "tenant_id"],
            [f"{APP_SCHEMA}.attachments.id", f"{APP_SCHEMA}.attachments.tenant_id"],
            name="fk_message_attachments_attachment_tenant",
        ),
        Index("uq_message_attachments_position", "message_id", "position", unique=True),
        {"schema": APP_SCHEMA},
    )

    message_id: UUID = Field(primary_key=True)
    attachment_id: UUID = Field(primary_key=True, unique=True)
    tenant_id: UUID = Field(index=True)
    position: int = Field()
    created_at: datetime = utc_datetime_field(default_factory=utc_now)
