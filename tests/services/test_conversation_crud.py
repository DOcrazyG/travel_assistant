"""Unit tests for conversation-specific CRUD behavior."""

import asyncio
from uuid import uuid4

import pytest

from app.core.errors import APIError
from app.models.conversations import Conversation
from app.models.operations import DataDeletionRequest
from app.schemas.conversations import ConversationCreate
from app.services.crud.conversations import ConversationCRUD


class FakeResult:
    def __init__(self, conversation: Conversation | None = None) -> None:
        self.conversation = conversation

    def one_or_none(self) -> Conversation | None:
        return self.conversation

    def all(self) -> list[Conversation]:
        return [self.conversation] if self.conversation is not None else []


class FakeSession:
    def __init__(self, result: FakeResult | None = None) -> None:
        self.result = result or FakeResult()
        self.added: list[object] = []
        self.commits = 0
        self.flushes = 0
        self.refreshed: list[object] = []

    def add(self, entity: object) -> None:
        self.added.append(entity)

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, entity: object) -> None:
        self.refreshed.append(entity)

    async def exec(self, _: object) -> FakeResult:
        return self.result


def crud_for(session: FakeSession, user_id: object) -> ConversationCRUD:
    return ConversationCRUD(session, user_id)  # type: ignore[arg-type]


def test_create_sets_the_immutable_user_scope_and_commits() -> None:
    user_id = uuid4()
    session = FakeSession()
    crud = crud_for(session, user_id)

    conversation = asyncio.run(
        crud.create(ConversationCreate(title="杭州周末", metadata={"locale": "zh-CN"}))
    )

    assert conversation.user_id == user_id
    assert conversation.title_source == "user"
    assert conversation.metadata_ == {"locale": "zh-CN"}
    assert session.added == [conversation]
    assert session.commits == 1
    assert session.refreshed == [conversation]


def test_require_hides_a_missing_or_unowned_conversation() -> None:
    crud = crud_for(FakeSession(), uuid4())

    with pytest.raises(APIError) as error:
        asyncio.run(crud.require(uuid4()))

    assert error.value.status_code == 404
    assert error.value.code == "conversation_not_found"


def test_delete_marks_the_aggregate_and_queues_a_physical_purge() -> None:
    user_id = uuid4()
    conversation = Conversation(user_id=user_id)
    session = FakeSession()
    crud = crud_for(session, user_id)

    asyncio.run(crud.delete(conversation))

    assert conversation.status == "deleted"
    assert conversation.deleted_at is not None
    assert conversation.purge_after_at is not None
    assert session.commits == 1
    assert len(session.added) == 1
    request = session.added[0]
    assert isinstance(request, DataDeletionRequest)
    assert request.target_id == conversation.id
