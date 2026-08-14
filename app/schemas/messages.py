"""Request and response DTOs for canonical conversation-message persistence."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.pagination import OffsetPage


class MessageRead(BaseModel):
    """A canonical persisted message suitable for history rendering."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sequence: int
    role: Literal["user", "assistant", "system", "tool"]
    content: list[dict[str, Any]]
    rendered_text: str | None
    content_status: Literal["complete", "partial", "failed", "redacted"]
    model_alias: str | None
    token_count: int | None
    created_at: datetime
    updated_at: datetime


class MessagePage(BaseModel):
    """A page of canonical messages for one authorized conversation."""

    data: list[MessageRead]
    page: OffsetPage


class MessageCreate(BaseModel):
    """A message prepared by the P2 execution flow after it assigns a sequence."""

    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    role: Literal["user", "assistant", "system", "tool"]
    content: list[dict[str, Any]]
    rendered_text: str | None = None
    content_status: Literal["complete", "partial", "failed", "redacted"] = "complete"
    agent_run_id: UUID | None = None
    model_alias: str | None = Field(default=None, max_length=200)
    token_count: int | None = Field(default=None, ge=0)


class MessageUpdate(BaseModel):
    """Fields that may change while an assistant response is being persisted."""

    model_config = ConfigDict(extra="forbid")

    content: list[dict[str, Any]] = Field(default_factory=list)
    rendered_text: str | None = None
    content_status: Literal["complete", "partial", "failed", "redacted"] | None = None
    token_count: int | None = Field(default=None, ge=0)


class MessageSubmission(BaseModel):
    """One new user message accepted by the single-Agent endpoint."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=20_000)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=20)
    stream: bool = False

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("content must not be empty")
        return normalized

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, str]) -> dict[str, str]:
        for key, item in value.items():
            if not key.strip() or len(key) > 64:
                raise ValueError("metadata keys must contain 1 to 64 characters")
            if len(item) > 200:
                raise ValueError("metadata values must not exceed 200 characters")
        return value


class MessageSubmissionResponse(BaseModel):
    """The durable completion returned by a non-streaming conversation invocation."""

    conversation_id: UUID
    run_id: UUID
    message: MessageRead
