"""Pydantic DTOs for the authenticated conversation REST API."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.messages import MessagePage
from app.schemas.pagination import OffsetPage


class ConversationCreate(BaseModel):
    """Optional display data for an explicitly created empty conversation."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=500)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=20)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        """Avoid saving empty display titles."""

        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("title must not be empty")
        return normalized

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, str]) -> dict[str, str]:
        """Keep UI context bounded and scalar; it is not a secrets channel."""

        for key, item in value.items():
            if not key.strip() or len(key) > 64:
                raise ValueError("metadata keys must contain 1 to 64 characters")
            if len(item) > 200:
                raise ValueError("metadata values must not exceed 200 characters")
        return value


class ConversationUpdate(BaseModel):
    """The currently permitted mutable fields for a caller-owned conversation."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=500)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        """Apply the same display-title normalization as explicit creation."""

        return ConversationCreate.normalize_title(value)


class ConversationRead(BaseModel):
    """Public conversation representation; the internal thread ID is excluded."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str | None
    title_source: Literal["system", "user"] | None
    status: Literal["active", "archived"]
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    last_message_at: datetime | None
    latest_message_sequence: int
    created_at: datetime
    updated_at: datetime


class ConversationPage(BaseModel):
    """A page of the current user's conversations."""

    data: list[ConversationRead]
    page: OffsetPage


class ConversationDetail(ConversationRead):
    """Conversation metadata and its requested initial message page."""

    messages: MessagePage


class ErrorResponse(BaseModel):
    """The safe, Problem Details-like error envelope returned by this API."""

    code: str
    message: str
    request_id: str
    details: dict[str, Any] | None = None
