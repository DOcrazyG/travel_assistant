"""Shared SQLModel helpers for PostgreSQL-backed application tables."""

from datetime import UTC, datetime
from secrets import randbits
from time import time_ns
from typing import Any, cast
from uuid import UUID

from sqlalchemy import DateTime
from sqlmodel import Field, SQLModel

APP_SCHEMA = "app"


def utc_now() -> datetime:
    """Return a timezone-aware timestamp suitable for persisted audit fields."""

    return datetime.now(UTC)


def new_uuid7() -> UUID:
    """Generate an RFC 9562 UUIDv7 on Python versions without ``uuid.uuid7``."""

    timestamp_ms = time_ns() // 1_000_000
    value = (timestamp_ms << 80) | (0x7 << 76) | (randbits(12) << 64) | (0b10 << 62) | randbits(62)
    return UUID(int=value)


def utc_datetime_field(*args: Any, **kwargs: Any) -> Any:
    """Create a field persisted as PostgreSQL ``timestamptz``."""

    return Field(*args, sa_type=cast(type[Any], DateTime(timezone=True)), **kwargs)


class TimestampedModel(SQLModel):
    """Common application-managed creation and update timestamps."""

    created_at: datetime = utc_datetime_field(default_factory=utc_now, nullable=False)
    updated_at: datetime = utc_datetime_field(default_factory=utc_now, nullable=False)
