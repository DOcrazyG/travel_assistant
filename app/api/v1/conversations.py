"""Authenticated REST endpoints for conversation creation and history retrieval."""

from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import bind_context
from app.dependencies.auth import get_current_user
from app.dependencies.database import get_session
from app.dependencies.rate_limit import limit_conversation_write
from app.models.conversations import Conversation
from app.models.messages import Message
from app.models.users import User
from app.schemas.conversations import (
    ConversationCreate,
    ConversationDetail,
    ConversationPage,
    ConversationRead,
)
from app.schemas.messages import MessagePage, MessageRead
from app.schemas.pagination import OffsetPage
from app.services.crud.conversations import ConversationCRUD
from app.services.crud.messages import MessageCRUD

router = APIRouter(prefix="/conversations", tags=["conversations"])


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
