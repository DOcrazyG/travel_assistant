"""Authenticated REST endpoints for conversation creation and history retrieval."""

import json
from collections.abc import AsyncIterator, Sequence
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import APIError
from app.core.logging import bind_context
from app.dependencies.auth import get_current_user
from app.dependencies.database import get_session
from app.dependencies.rate_limit import limit_conversation_write
from app.dependencies.services import (
    get_conversation_execution_service,
    get_idempotency_service,
)
from app.models.agent_runs import AgentRun
from app.models.conversations import Conversation
from app.models.messages import Message
from app.models.users import User
from app.schemas.conversation_requests import ConversationMessageCreateRequest
from app.schemas.conversations import (
    ConversationCreate,
    ConversationDetail,
    ConversationPage,
    ConversationRead,
)
from app.schemas.messages import (
    MessagePage,
    MessageRead,
)
from app.schemas.pagination import OffsetPage
from app.schemas.responses import (
    ConversationResponse,
    ErrorEvent,
    ResponseCompletedEvent,
    ResponseContentPartAddedEvent,
    ResponseContentPartDoneEvent,
    ResponseConversation,
    ResponseCreatedEvent,
    ResponseFailedEvent,
    ResponseInProgressEvent,
    ResponseOutputItem,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseOutputTextDeltaEvent,
    ResponseOutputTextDoneEvent,
    ResponseStatus,
)
from app.services.conversation_execution import ConversationExecutionService
from app.services.crud.conversations import ConversationCRUD
from app.services.crud.messages import MessageCRUD
from app.services.idempotency import IdempotencyReservation, IdempotencyService

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _replay_failure(reservation: IdempotencyReservation) -> None:
    """Raise the safe terminal error stored for an idempotent replay."""

    record = reservation.record
    if record.status != "failed":
        return
    snapshot = record.response_snapshot or {}
    raise APIError(
        record.response_status or status.HTTP_500_INTERNAL_SERVER_ERROR,
        str(snapshot.get("code", "internal_error")),
        str(snapshot.get("message", "An unexpected error occurred.")),
        details=snapshot.get("details"),
    )


def _sse_event(event: BaseModel) -> str:
    """Serialize one typed Responses-style Server-Sent Event payload."""

    payload = event.model_dump(mode="json")
    event_type = str(payload["type"])
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sse_response(events: AsyncIterator[str]) -> StreamingResponse:
    """Return an unbuffered event stream with browser-safe response headers."""

    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _conversation_read(conversation: object) -> ConversationRead:
    """Serialize the public conversation view without leaking its graph thread ID."""

    return ConversationRead.model_validate(conversation)


def _message_page(
    items: Sequence[Message],
    *,
    offset: int,
    limit: int,
    next_offset: int | None,
) -> MessagePage:
    """Serialize a single message page from a service result."""

    return MessagePage(
        data=[MessageRead.model_validate(item) for item in items],
        page=OffsetPage(offset=offset, limit=limit, next_offset=next_offset),
    )


def _response_output(message: Message, *, status: str) -> ResponseOutputMessage:
    """Map the canonical transcript record to the text output item public API."""

    item_status = "completed" if status == "completed" else "incomplete"
    if status == "in_progress":
        item_status = "in_progress"
    return ResponseOutputMessage(
        id=message.id,
        status=item_status,
        content=[ResponseOutputText(text=message.rendered_text or "")],
    )


def _response(
    *,
    conversation: Conversation,
    run: AgentRun,
    status_value: ResponseStatus,
    message: Message | None = None,
) -> ConversationResponse:
    """Create the stable public Response envelope from application records."""

    created_at = int(run.created_at.timestamp())
    output: list[ResponseOutputItem] = (
        [] if message is None else [_response_output(message, status=status_value)]
    )
    return ConversationResponse(
        id=run.id,
        created_at=created_at,
        model=run.model_alias or "travel-assistant",
        status=status_value,
        output=output,
        conversation=ResponseConversation(id=conversation.id),
    )


def _crud(session: AsyncSession, user: User) -> ConversationCRUD:
    """Construct the pure CRUD service from explicitly injected request resources."""

    return ConversationCRUD(session, user.id)


def _message_crud(session: AsyncSession, conversation_id: UUID) -> MessageCRUD:
    """Construct message CRUD only after the parent conversation has been authorized."""

    return MessageCRUD(session, conversation_id)


def _bind_conversation_context(request: Request, conversation: Conversation) -> None:
    """Expose the public conversation identifier to logs for this request only."""

    request.state.conversation_id = conversation.id
    bind_context(conversation_id=str(conversation.id))


@router.post(
    "",
    response_model=ConversationRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_conversation_write)],
)
async def create_conversation(
    payload: ConversationCreate,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ConversationRead:
    """Explicitly create an empty, caller-owned conversation."""

    conversation = await _crud(session, current_user).create(payload)
    _bind_conversation_context(request, conversation)
    return _conversation_read(conversation)


@router.get("", response_model=ConversationPage)
async def list_conversations(
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> ConversationPage:
    """List the current user's accessible conversations in most-recent-first order."""

    page = await _crud(session, current_user).get_page(offset=offset, limit=limit)
    return ConversationPage(
        data=[_conversation_read(conversation) for conversation in page.items],
        page=OffsetPage(offset=offset, limit=limit, next_offset=page.next_offset),
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> ConversationDetail:
    """Return an owned conversation and the requested first page of its history."""

    crud = _crud(session, current_user)
    conversation = await crud.require(conversation_id)
    _bind_conversation_context(request, conversation)
    page = await _message_crud(session, conversation.id).get_page(offset=offset, limit=limit)
    conversation_data = _conversation_read(conversation).model_dump()
    conversation_data["metadata_"] = conversation_data.pop("metadata")
    return ConversationDetail(
        **conversation_data,
        messages=_message_page(
            page.items,
            offset=offset,
            limit=limit,
            next_offset=page.next_offset,
        ),
    )


@router.get("/{conversation_id}/messages", response_model=MessagePage)
async def list_messages(
    conversation_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> MessagePage:
    """Return one page of an owned conversation's canonical message history."""

    crud = _crud(session, current_user)
    conversation = await crud.require(conversation_id)
    _bind_conversation_context(request, conversation)
    page = await _message_crud(session, conversation.id).get_page(offset=offset, limit=limit)
    return _message_page(
        page.items,
        offset=offset,
        limit=limit,
        next_offset=page.next_offset,
    )


@router.post(
    "/{conversation_id}/messages",
    response_model=ConversationResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(limit_conversation_write)],
)
async def submit_message(
    conversation_id: UUID,
    payload: ConversationMessageCreateRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    execution_service: Annotated[
        ConversationExecutionService, Depends(get_conversation_execution_service)
    ],
    idempotency_service: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ConversationResponse | StreamingResponse:
    """Create one Responses-style Agent turn as JSON or an SSE event stream."""

    conversation = await _crud(session, current_user).require(conversation_id)
    _bind_conversation_context(request, conversation)
    if idempotency_key is None:
        raise APIError(400, "missing_idempotency_key", "Idempotency-Key is required.")
    if not payload.input.is_text_only:
        raise APIError(
            422,
            "input_content_not_supported",
            "Image and file inputs are defined by the API but not enabled by the current Agent.",
        )
    reservation = await idempotency_service.begin(
        user_id=current_user.id,
        http_method=request.method,
        route=request.url.path,
        idempotency_key=idempotency_key,
        payload=payload.model_dump(mode="json"),
    )
    if reservation.replay:
        _replay_failure(reservation)
        replay = ConversationResponse.model_validate(reservation.record.response_snapshot)
        if payload.stream:

            async def replay_events() -> AsyncIterator[str]:
                yield _sse_event(ResponseCompletedEvent(sequence_number=0, response=replay))

            return _sse_response(replay_events())
        return replay

    if payload.stream:

        async def stream_events() -> AsyncIterator[str]:
            sequence_number = 0
            active_response: ConversationResponse | None = None
            active_message: Message | None = None
            try:
                async for event in execution_service.stream(
                    conversation=conversation,
                    user_id=current_user.id,
                    content=payload.input.rendered_text,
                ):
                    if event.event == "status":
                        active_message = event.message
                        active_response = _response(
                            conversation=conversation,
                            run=event.run,
                            status_value="in_progress",
                        )
                        yield _sse_event(
                            ResponseCreatedEvent(
                                sequence_number=sequence_number,
                                response=active_response,
                            )
                        )
                        sequence_number += 1
                        yield _sse_event(
                            ResponseInProgressEvent(
                                sequence_number=sequence_number,
                                response=active_response,
                            )
                        )
                        sequence_number += 1
                        output_item = _response_output(event.message, status="in_progress")
                        yield _sse_event(
                            ResponseOutputItemAddedEvent(
                                sequence_number=sequence_number,
                                item=output_item,
                            )
                        )
                        sequence_number += 1
                        yield _sse_event(
                            ResponseContentPartAddedEvent(
                                sequence_number=sequence_number,
                                item_id=event.message.id,
                                part=ResponseOutputText(text=""),
                            )
                        )
                        sequence_number += 1
                    elif event.event == "token" and event.delta is not None:
                        yield _sse_event(
                            ResponseOutputTextDeltaEvent(
                                sequence_number=sequence_number,
                                item_id=event.message.id,
                                delta=event.delta,
                            )
                        )
                        sequence_number += 1
                    elif event.event == "final" and event.result is not None:
                        response = _response(
                            conversation=conversation,
                            run=event.result.run,
                            status_value="completed",
                            message=event.result.message,
                        )
                        await idempotency_service.complete(
                            reservation.record,
                            response_status=status.HTTP_200_OK,
                            response_snapshot=response.model_dump(mode="json"),
                            conversation_id=conversation.id,
                            agent_run_id=event.result.run.id,
                        )
                        answer = event.result.message.rendered_text or ""
                        yield _sse_event(
                            ResponseOutputTextDoneEvent(
                                sequence_number=sequence_number,
                                item_id=event.result.message.id,
                                text=answer,
                            )
                        )
                        sequence_number += 1
                        output_item = _response_output(event.result.message, status="completed")
                        yield _sse_event(
                            ResponseContentPartDoneEvent(
                                sequence_number=sequence_number,
                                item_id=event.result.message.id,
                                part=output_item.content[0],
                            )
                        )
                        sequence_number += 1
                        yield _sse_event(
                            ResponseOutputItemDoneEvent(
                                sequence_number=sequence_number,
                                item=output_item,
                            )
                        )
                        sequence_number += 1
                        yield _sse_event(
                            ResponseCompletedEvent(
                                sequence_number=sequence_number,
                                response=response,
                            )
                        )
            except APIError as error:
                await idempotency_service.fail(
                    reservation.record,
                    response_status=error.status_code,
                    response_snapshot={
                        "code": error.code,
                        "message": error.message,
                        "details": error.details,
                    },
                )
                if active_response is not None:
                    yield _sse_event(
                        ResponseFailedEvent(
                            sequence_number=sequence_number,
                            response=_response(
                                conversation=conversation,
                                run=event.run,
                                status_value="failed",
                                message=active_message,
                            ),
                        )
                    )
                    sequence_number += 1
                yield _sse_event(
                    ErrorEvent(
                        sequence_number=sequence_number,
                        code=error.code,
                        message=error.message,
                    )
                )
            except Exception:
                await idempotency_service.fail(
                    reservation.record,
                    response_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    response_snapshot={
                        "code": "internal_error",
                        "message": "An unexpected error occurred.",
                    },
                )
                if active_response is not None:
                    yield _sse_event(
                        ResponseFailedEvent(
                            sequence_number=sequence_number,
                            response=_response(
                                conversation=conversation,
                                run=event.run,
                                status_value="failed",
                                message=active_message,
                            ),
                        )
                    )
                    sequence_number += 1
                yield _sse_event(
                    ErrorEvent(
                        sequence_number=sequence_number,
                        code="internal_error",
                        message="An unexpected error occurred.",
                    )
                )

        return _sse_response(stream_events())

    try:
        result = await execution_service.execute(
            conversation=conversation,
            user_id=current_user.id,
            content=payload.input.rendered_text,
        )
    except APIError as error:
        await idempotency_service.fail(
            reservation.record,
            response_status=error.status_code,
            response_snapshot={
                "code": error.code,
                "message": error.message,
                "details": error.details,
            },
        )
        raise
    except Exception:
        await idempotency_service.fail(
            reservation.record,
            response_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            response_snapshot={
                "code": "internal_error",
                "message": "An unexpected error occurred.",
            },
        )
        raise
    response = _response(
        conversation=conversation,
        run=result.run,
        status_value="completed",
        message=result.message,
    )
    await idempotency_service.complete(
        reservation.record,
        response_status=status.HTTP_200_OK,
        response_snapshot=response.model_dump(mode="json"),
        conversation_id=conversation.id,
        agent_run_id=result.run.id,
    )
    return response


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(limit_conversation_write)],
)
async def delete_conversation(
    conversation_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    """Immediately hide an owned conversation and schedule its physical purge."""

    crud = _crud(session, current_user)
    conversation = await crud.require(conversation_id)
    _bind_conversation_context(request, conversation)
    await crud.delete(conversation)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
