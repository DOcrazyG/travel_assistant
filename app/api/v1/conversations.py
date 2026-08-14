"""Authenticated REST endpoints for conversation creation and history retrieval."""

import json
from collections.abc import AsyncIterator, Sequence
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import StreamingResponse
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
from app.models.conversations import Conversation
from app.models.messages import Message
from app.models.users import User
from app.schemas.conversations import (
    ConversationCreate,
    ConversationDetail,
    ConversationPage,
    ConversationRead,
)
from app.schemas.messages import (
    MessagePage,
    MessageRead,
    MessageSubmission,
    MessageSubmissionResponse,
)
from app.schemas.pagination import OffsetPage
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


def _sse_event(event: str, data: dict[str, Any]) -> str:
    """Serialize one safe Server-Sent Event payload."""

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


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
    response_model=MessageSubmissionResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(limit_conversation_write)],
)
async def submit_message(
    conversation_id: UUID,
    payload: MessageSubmission,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    execution_service: Annotated[
        ConversationExecutionService, Depends(get_conversation_execution_service)
    ],
    idempotency_service: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> MessageSubmissionResponse | StreamingResponse:
    """Run one idempotent Agent turn as JSON or an SSE token stream."""

    conversation = await _crud(session, current_user).require(conversation_id)
    _bind_conversation_context(request, conversation)
    if idempotency_key is None:
        raise APIError(400, "missing_idempotency_key", "Idempotency-Key is required.")
    reservation = await idempotency_service.begin(
        user_id=current_user.id,
        http_method=request.method,
        route=request.url.path,
        idempotency_key=idempotency_key,
        payload=payload.model_dump(mode="json"),
    )
    if reservation.replay:
        _replay_failure(reservation)
        replay = MessageSubmissionResponse.model_validate(reservation.record.response_snapshot)
        if payload.stream:

            async def replay_events() -> AsyncIterator[str]:
                yield _sse_event(
                    "final",
                    {
                        "request_id": str(getattr(request.state, "request_id", "")),
                        **replay.model_dump(mode="json"),
                    },
                )

            return _sse_response(replay_events())
        return replay

    if payload.stream:

        async def stream_events() -> AsyncIterator[str]:
            request_id = str(getattr(request.state, "request_id", ""))
            try:
                async for event in execution_service.stream(
                    conversation=conversation,
                    user_id=current_user.id,
                    content=payload.content,
                ):
                    common = {
                        "request_id": request_id,
                        "conversation_id": str(conversation.id),
                        "run_id": str(event.run.id),
                    }
                    if event.event == "status":
                        yield _sse_event("status", {**common, "status": "running"})
                    elif event.event == "token" and event.delta is not None:
                        yield _sse_event("token", {**common, "delta": event.delta})
                    elif event.event == "final" and event.result is not None:
                        response = MessageSubmissionResponse(
                            conversation_id=conversation.id,
                            run_id=event.result.run.id,
                            message=MessageRead.model_validate(event.result.message),
                        )
                        await idempotency_service.complete(
                            reservation.record,
                            response_status=status.HTTP_200_OK,
                            response_snapshot=response.model_dump(mode="json"),
                            conversation_id=conversation.id,
                            agent_run_id=event.result.run.id,
                        )
                        yield _sse_event("final", {**common, **response.model_dump(mode="json")})
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
                yield _sse_event(
                    "error",
                    {
                        "request_id": request_id,
                        "code": error.code,
                        "message": error.message,
                    },
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
                yield _sse_event(
                    "error",
                    {
                        "request_id": request_id,
                        "code": "internal_error",
                        "message": "An unexpected error occurred.",
                    },
                )

        return _sse_response(stream_events())

    try:
        result = await execution_service.execute(
            conversation=conversation,
            user_id=current_user.id,
            content=payload.content,
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
    response = MessageSubmissionResponse(
        conversation_id=conversation.id,
        run_id=result.run.id,
        message=MessageRead.model_validate(result.message),
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
