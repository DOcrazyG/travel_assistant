"""Application request DTOs for the authenticated conversation API.

They intentionally expose a smaller surface than ``responses.py``: callers may
submit one user message, while system/developer messages, tool definitions, and
tool outputs remain server-owned protocol concerns.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.responses import ResponseInputMessage


class ConversationUserInputMessage(ResponseInputMessage):
    """The only client-supplied role accepted by the conversation route."""

    role: Literal["user"] = "user"


class ConversationMessageCreateRequest(BaseModel):
    """The single new input and transport options for one conversation turn."""

    model_config = ConfigDict(extra="forbid")

    model: Literal["travel-assistant"] = "travel-assistant"
    input: ConversationUserInputMessage
    stream: bool = False
    metadata: dict[str, str] = Field(default_factory=dict, max_length=20)

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, str]) -> dict[str, str]:
        for key, item in value.items():
            if not key.strip() or len(key) > 64:
                raise ValueError("metadata keys must contain 1 to 64 characters")
            if len(item) > 200:
                raise ValueError("metadata values must not exceed 200 characters")
        return value
