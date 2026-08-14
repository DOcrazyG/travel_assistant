"""Tests for the Responses-inspired public conversation type system."""

import pytest
from pydantic import ValidationError

from app.schemas.conversation_requests import ConversationMessageCreateRequest
from app.schemas.responses import (
    FunctionToolDefinition,
    ResponseCreateParams,
    ResponseFunctionCallOutput,
    ResponseFunctionToolCall,
    ResponseInputFile,
    ResponseInputImage,
    ResponseInputMessage,
    ResponseInputText,
)


def test_input_message_accepts_text_image_and_file_content_parts() -> None:
    message = ResponseInputMessage(
        role="user",
        content=[
            ResponseInputText(text="这张图里是什么？"),
            ResponseInputImage(image_url="https://example.test/photo.jpg"),
            ResponseInputFile(file_id="file_123", filename="itinerary.pdf"),
        ],
    )

    assert message.rendered_text == "这张图里是什么？"
    assert not message.is_text_only
    assert [part.type for part in message.content] == ["input_text", "input_image", "input_file"]


def test_protocol_message_keeps_system_and_developer_roles_out_of_user_requests() -> None:
    message = ResponseInputMessage(
        role="developer",
        content=[ResponseInputText(text="Use concise Chinese.")],
    )

    assert message.role == "developer"


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({"image_url": "https://example.test/a.jpg", "file_id": "file_123"}, "exactly one"),
        ({}, "exactly one"),
    ],
)
def test_input_image_requires_one_source(payload: dict[str, str], error: str) -> None:
    with pytest.raises(ValidationError, match=error):
        ResponseInputImage.model_validate(payload)


def test_function_tool_definition_and_call_round_trip() -> None:
    tool = FunctionToolDefinition(
        name="search_flights",
        description="Search available flights.",
        parameters={"type": "object", "properties": {"city": {"type": "string"}}},
        strict=True,
    )
    call = ResponseFunctionToolCall(
        id="fc_123",
        call_id="call_123",
        name=tool.name,
        arguments='{"city":"SHA"}',
    )
    result = ResponseFunctionCallOutput(
        call_id=call.call_id,
        output='{"flights":[]}',
    )

    assert tool.type == "function"
    assert call.type == "function_call"
    assert result.type == "function_call_output"


def test_protocol_parameters_are_broader_than_the_public_conversation_request() -> None:
    tool = FunctionToolDefinition(
        name="search_flights",
        parameters={"type": "object"},
        strict=True,
    )
    protocol_params = ResponseCreateParams(
        model="provider-model",
        input=[
            ResponseInputMessage(
                role="developer",
                content=[ResponseInputText(text="Use concise Chinese.")],
            )
        ],
        tools=[tool],
    )

    assert protocol_params.tools == [tool]
    with pytest.raises(ValidationError):
        ConversationMessageCreateRequest.model_validate(
            {
                "input": {"role": "user", "content": [{"type": "input_text", "text": "你好"}]},
                "tools": [tool.model_dump()],
            }
        )
