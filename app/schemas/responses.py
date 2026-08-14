"""Responses-style DTOs for one turn in a persisted conversation.

These model the durable conversation subset of the stable OpenAI Responses API.
The types intentionally cover multimodal input and function-calling records even
where the current single-Agent runtime has not enabled their execution yet.
Database transcript DTOs remain in ``messages.py``.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ResponseStatus = Literal["queued", "in_progress", "completed", "failed", "incomplete", "cancelled"]


class ResponseInputText(BaseModel):
    """One text content part submitted by the caller."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["input_text"] = "input_text"
    text: str = Field(min_length=1, max_length=20_000)

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("text must not be empty")
        return normalized


class ResponseInputImage(BaseModel):
    """An image referenced by URL or an uploaded-file identifier."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["input_image"] = "input_image"
    detail: Literal["auto", "low", "high"] = "auto"
    image_url: str | None = Field(default=None, min_length=1, max_length=10_000)
    file_id: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def require_one_source(self) -> ResponseInputImage:
        if (self.image_url is None) == (self.file_id is None):
            raise ValueError("input_image requires exactly one of image_url or file_id")
        return self


class ResponseInputFile(BaseModel):
    """A file referenced by ID, URL, or inline encoded data."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["input_file"] = "input_file"
    file_id: str | None = Field(default=None, min_length=1, max_length=500)
    file_url: str | None = Field(default=None, min_length=1, max_length=10_000)
    file_data: str | None = Field(default=None, min_length=1, max_length=20_000_000)
    filename: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def require_a_source(self) -> ResponseInputFile:
        if self.file_id is None and self.file_url is None and self.file_data is None:
            raise ValueError("input_file requires file_id, file_url, or file_data")
        return self


ResponseInputContent = Annotated[
    ResponseInputText | ResponseInputImage | ResponseInputFile,
    Field(discriminator="type"),
]


class ResponseInputMessage(BaseModel):
    """A protocol message whose content parts may be text, images, or files."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["message"] = "message"
    role: Literal["user", "system", "developer"]
    content: list[ResponseInputContent] = Field(min_length=1, max_length=20)

    @property
    def rendered_text(self) -> str:
        """Return textual parts for history projections and the current Agent."""

        return "\n".join(part.text for part in self.content if isinstance(part, ResponseInputText))

    @property
    def is_text_only(self) -> bool:
        """Whether the current text-only runtime can execute this input losslessly."""

        return all(isinstance(part, ResponseInputText) for part in self.content)


class ResponseFunctionCallOutput(BaseModel):
    """A function result supplied as an input item for a subsequent response."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["function_call_output"] = "function_call_output"
    call_id: str = Field(min_length=1, max_length=500)
    output: str | list[ResponseInputContent]
    id: str | None = Field(default=None, min_length=1, max_length=500)
    status: Literal["in_progress", "completed", "incomplete"] | None = None


class FunctionToolDefinition(BaseModel):
    """A server-owned function contract that a future Agent may choose to call."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["function"] = "function"
    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z_][A-Za-z0-9_-]*$")
    parameters: dict[str, Any] | None = None
    strict: bool | None = None
    description: str | None = Field(default=None, max_length=2_000)
    output_schema: dict[str, Any] | None = None


ResponseToolDefinition = Annotated[FunctionToolDefinition, Field(discriminator="type")]


class ResponseOutputText(BaseModel):
    """A finalized or in-progress text part in an assistant output item."""

    type: Literal["output_text"] = "output_text"
    text: str
    annotations: list[object] = Field(default_factory=list)


class ResponseOutputRefusal(BaseModel):
    """A model refusal content part, kept distinct from normal output text."""

    type: Literal["refusal"] = "refusal"
    refusal: str


ResponseOutputContent = Annotated[
    ResponseOutputText | ResponseOutputRefusal,
    Field(discriminator="type"),
]


class ResponseOutputMessage(BaseModel):
    """The text-only assistant message output by the current Agent."""

    id: UUID
    type: Literal["message"] = "message"
    role: Literal["assistant"] = "assistant"
    status: Literal["in_progress", "completed", "incomplete"]
    content: list[ResponseOutputContent]


class ResponseFunctionToolCall(BaseModel):
    """A function invocation requested by a model response."""

    type: Literal["function_call"] = "function_call"
    arguments: str
    call_id: str
    name: str
    id: str | None = None
    status: Literal["in_progress", "completed", "incomplete"] | None = None


ResponseOutputItem = Annotated[
    ResponseOutputMessage | ResponseFunctionToolCall,
    Field(discriminator="type"),
]


ResponseInputItem = Annotated[
    ResponseInputMessage | ResponseFunctionToolCall | ResponseFunctionCallOutput,
    Field(discriminator="type"),
]


class ResponseCreateParams(BaseModel):
    """Protocol-level Responses create parameters for a provider adapter.

    This deliberately has the broader OpenAI-style input and tool surface. It
    is not the same object accepted by the authenticated conversation route.
    """

    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=200)
    input: str | list[ResponseInputItem]
    stream: bool = False
    metadata: dict[str, str] = Field(default_factory=dict, max_length=16)
    tools: list[ResponseToolDefinition] = Field(default_factory=list, max_length=64)
    parallel_tool_calls: bool | None = None

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, str]) -> dict[str, str]:
        for key, item in value.items():
            if not key.strip() or len(key) > 64:
                raise ValueError("metadata keys must contain 1 to 64 characters")
            if len(item) > 512:
                raise ValueError("metadata values must not exceed 512 characters")
        return value


class ResponseConversation(BaseModel):
    """Application-owned conversation reference carried by a response."""

    id: UUID
    object: Literal["conversation"] = "conversation"


class ResponseUsage(BaseModel):
    """Provider token accounting when it becomes available."""

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class ConversationResponse(BaseModel):
    """One Responses-style model invocation backed by an Agent run."""

    id: UUID
    object: Literal["response"] = "response"
    created_at: int = Field(ge=0)
    model: str
    status: ResponseStatus
    output: list[ResponseOutputItem] = Field(default_factory=list)
    conversation: ResponseConversation
    usage: ResponseUsage | None = None


class _ResponseStreamEvent(BaseModel):
    """Fields common to all ordered Responses-style stream events."""

    sequence_number: int = Field(ge=0)


class ResponseCreatedEvent(_ResponseStreamEvent):
    type: Literal["response.created"] = "response.created"
    response: ConversationResponse


class ResponseInProgressEvent(_ResponseStreamEvent):
    type: Literal["response.in_progress"] = "response.in_progress"
    response: ConversationResponse


class ResponseOutputItemAddedEvent(_ResponseStreamEvent):
    type: Literal["response.output_item.added"] = "response.output_item.added"
    output_index: Literal[0] = 0
    item: ResponseOutputItem


class ResponseContentPartAddedEvent(_ResponseStreamEvent):
    type: Literal["response.content_part.added"] = "response.content_part.added"
    output_index: Literal[0] = 0
    item_id: UUID
    content_index: Literal[0] = 0
    part: ResponseOutputContent


class ResponseOutputTextDeltaEvent(_ResponseStreamEvent):
    type: Literal["response.output_text.delta"] = "response.output_text.delta"
    output_index: Literal[0] = 0
    item_id: UUID
    content_index: Literal[0] = 0
    delta: str


class ResponseOutputTextDoneEvent(_ResponseStreamEvent):
    type: Literal["response.output_text.done"] = "response.output_text.done"
    output_index: Literal[0] = 0
    item_id: UUID
    content_index: Literal[0] = 0
    text: str


class ResponseContentPartDoneEvent(_ResponseStreamEvent):
    type: Literal["response.content_part.done"] = "response.content_part.done"
    output_index: Literal[0] = 0
    item_id: UUID
    content_index: Literal[0] = 0
    part: ResponseOutputContent


class ResponseOutputItemDoneEvent(_ResponseStreamEvent):
    type: Literal["response.output_item.done"] = "response.output_item.done"
    output_index: Literal[0] = 0
    item: ResponseOutputItem


class ResponseFunctionCallArgumentsDeltaEvent(_ResponseStreamEvent):
    """An incremental JSON-arguments fragment for a function tool call."""

    type: Literal["response.function_call_arguments.delta"] = (
        "response.function_call_arguments.delta"
    )
    output_index: int = Field(ge=0)
    item_id: str
    delta: str


class ResponseFunctionCallArgumentsDoneEvent(_ResponseStreamEvent):
    """The completed arguments payload for a function tool call."""

    type: Literal["response.function_call_arguments.done"] = "response.function_call_arguments.done"
    output_index: int = Field(ge=0)
    item_id: str
    name: str
    arguments: str


class ResponseCompletedEvent(_ResponseStreamEvent):
    type: Literal["response.completed"] = "response.completed"
    response: ConversationResponse


class ResponseFailedEvent(_ResponseStreamEvent):
    type: Literal["response.failed"] = "response.failed"
    response: ConversationResponse


class ErrorEvent(_ResponseStreamEvent):
    """A terminal safe error, matching the Responses API's generic error event."""

    type: Literal["error"] = "error"
    code: str
    message: str


ResponseStreamEvent = Annotated[
    ResponseCreatedEvent
    | ResponseInProgressEvent
    | ResponseOutputItemAddedEvent
    | ResponseContentPartAddedEvent
    | ResponseOutputTextDeltaEvent
    | ResponseOutputTextDoneEvent
    | ResponseContentPartDoneEvent
    | ResponseOutputItemDoneEvent
    | ResponseFunctionCallArgumentsDeltaEvent
    | ResponseFunctionCallArgumentsDoneEvent
    | ResponseCompletedEvent
    | ResponseFailedEvent
    | ErrorEvent,
    Field(discriminator="type"),
]
