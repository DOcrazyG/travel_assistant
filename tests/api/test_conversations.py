"""Route-level tests for authenticated conversation API behavior and response shapes."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import conversations as conversations_api
from app.core.crud import PageResult
from app.dependencies.auth import get_current_user
from app.dependencies.database import get_session
from app.main import create_app
from app.models.conversations import Conversation
from app.models.messages import Message
from app.models.users import User
from app.schemas.conversations import ConversationCreate


class ConversationCRUDStub:
    def __init__(self, _: object, user_id: object) -> None:
        self.conversation = Conversation(user_id=user_id)  # type: ignore[arg-type]
        self.messages = [
            Message(
                conversation_id=self.conversation.id,
                sequence=1,
                role="user",
                content=[{"type": "text", "text": "你好"}],
                rendered_text="你好",
            )
        ]
        self.created: ConversationCreate | None = None

    async def create(self, payload: ConversationCreate) -> Conversation:
        self.created = payload
        self.conversation.title = payload.title
        self.conversation.title_source = "user" if payload.title is not None else None
        self.conversation.metadata_ = payload.metadata
        return self.conversation

    async def get_page(self, *, offset: int, limit: int) -> PageResult[Conversation]:
        return PageResult(items=[self.conversation], next_offset=None)

    async def require(self, _: object) -> Conversation:
        return self.conversation

    async def delete(self, _: Conversation) -> None:
        return None


class MessageCRUDStub:
    def __init__(self, messages: list[Message]) -> None:
        self.messages = messages

    async def get_page(self, *, offset: int, limit: int) -> PageResult[Message]:
        return PageResult(items=self.messages, next_offset=None)


def _user() -> User:
    return User(
        id=uuid4(),
        email="traveler@example.com",
        email_normalized="traveler@example.com",
        password_hash="not-returned",
    )


def test_conversation_routes_are_documented_and_never_expose_thread_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    service = ConversationCRUDStub(object(), user.id)
    app = create_app()

    async def current_user_override() -> User:
        return user

    async def session_override() -> object:
        return object()

    monkeypatch.setattr(conversations_api, "ConversationCRUD", lambda *_: service)
    monkeypatch.setattr(
        conversations_api,
        "MessageCRUD",
        lambda *_: MessageCRUDStub(service.messages),
    )
    app.dependency_overrides[get_current_user] = current_user_override
    app.dependency_overrides[get_session] = session_override
    client = TestClient(app)

    created = client.post("/api/v1/conversations", json={"title": "广州周末"})
    detail = client.get(f"/api/v1/conversations/{service.conversation.id}")
    listed = client.get("/api/v1/conversations")
    messages = client.get(f"/api/v1/conversations/{service.conversation.id}/messages")

    assert created.status_code == 201
    assert created.json()["title"] == "广州周末"
    assert "thread_id" not in created.json()
    assert detail.status_code == 200
    assert detail.json()["messages"]["data"][0]["rendered_text"] == "你好"
    assert listed.status_code == 200
    assert messages.status_code == 200
    assert client.delete(f"/api/v1/conversations/{service.conversation.id}").status_code == 204
    paths = app.openapi()["paths"]
    assert "/api/v1/conversations" in paths
    assert "/api/v1/conversations/{conversation_id}/messages" in paths


def test_conversation_request_validation_uses_the_shared_safe_error_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()
    user = _user()
    service = ConversationCRUDStub(object(), user.id)

    async def current_user_override() -> User:
        return user

    async def session_override() -> object:
        return object()

    monkeypatch.setattr(conversations_api, "ConversationCRUD", lambda *_: service)
    monkeypatch.setattr(
        conversations_api,
        "MessageCRUD",
        lambda *_: MessageCRUDStub(service.messages),
    )
    app.dependency_overrides[get_current_user] = current_user_override
    app.dependency_overrides[get_session] = session_override
    client = TestClient(app)

    response = client.post("/api/v1/conversations", json={"title": "   "})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert response.json()["message"] == "The request is invalid."
    assert response.json()["request_id"]
    assert response.headers["X-Request-ID"] == response.json()["request_id"]
