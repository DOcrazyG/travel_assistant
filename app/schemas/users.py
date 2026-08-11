"""Schemas for user creation, retrieval, and profile updates.

Passwords are deliberately accepted only by :class:`UserCreate`.  Password
changes are an authentication operation, rather than a generic CRUD update,
and will receive their own schema when that endpoint is introduced.
"""

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, SecretStr, field_validator, model_validator


def _normalize_email(value: str) -> str:
    """Return the canonical email form used for case-insensitive login."""

    normalized = value.strip().lower()
    local_part, separator, domain = normalized.rpartition("@")
    if (
        not separator
        or not local_part
        or not domain
        or "." not in domain
        or any(character.isspace() for character in normalized)
    ):
        raise ValueError("email must be a valid email address")
    if len(normalized) > 320:
        raise ValueError("email must not exceed 320 characters")
    return normalized


def _validate_password(value: SecretStr) -> SecretStr:
    """Apply the baseline password-length policy without exposing its value."""

    password = value.get_secret_value()
    if not 8 <= len(password) <= 64:
        raise ValueError("password must be between 8 and 64 characters")
    return value


class UserCreate(BaseModel):
    """Payload accepted when an account is registered."""

    model_config = ConfigDict(extra="forbid")

    email: str
    password: SecretStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Normalize the email before it reaches the service layer."""

        return _normalize_email(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        """Reject passwords outside the confirmed length policy."""

        return _validate_password(value)


class UserUpdate(BaseModel):
    """Mutable user profile fields.

    Email changes are intentionally separate from password changes.  The
    authentication service will later require verification before applying an
    email change once email verification is enabled.
    """

    model_config = ConfigDict(extra="forbid")

    email: str | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        """Normalize an explicitly supplied email address."""

        return _normalize_email(value) if value is not None else None

    @model_validator(mode="after")
    def require_mutation(self) -> Self:
        """Avoid accepting an update request that cannot change anything."""

        if self.email is None:
            raise ValueError("at least one mutable field must be supplied")
        return self


class UserRead(BaseModel):
    """Safe user representation returned from user-facing endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    status: str
    is_admin: bool
    email_verified_at: datetime | None
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
