"""Route-level tests for authenticated conversation API behavior and response shapes."""

from uuid import uuid4

import httpx
import pytest

from app.api.v1 import conversations as conversations_api
from app.core.crud import PageResult
from app.dependencies.auth import get_current_user
from app.dependencies.database import get_session
from app.dependencies.rate_limit import limit_conversation_write
from app.dependencies.services import (
    get_conversation_execution_service,
    get_idempotency_service,
)
from app.main import create_app
from app.models.agent_runs import AgentRun
from app.models.conversations import Conversation
from app.models.messages import Message
from app.models.users import User
from app.schemas.conversations import ConversationCreate
from app.services.conversation_execution import ConversationExecutionResult


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


class ExecutionServiceStub:
    async def execute(
        self,
        *,
        conversation: Conversation,
        user_id: object,
        content: str,
    ) -> ConversationExecutionResult:
        run = AgentRun(conversation_id=conversation.id, status="completed")
        message = Message(
            conversation_id=conversation.id,
            sequence=conversation.latest_message_sequence + 1,
            role="assistant",
            content=[{"type": "text", "text": f"回复：{content}"}],
            rendered_text=f"回复：{content}",
            agent_run_id=run.id,
        )
        return ConversationExecutionResult(run=run, message=message)


class IdempotencyServiceStub:
    async def begin(self, **_: object) -> object:
        class Reservation:
            replay = False
            record = object()

        return Reservation()

    async def complete(self, _: object, **__: object) -> None:
        return None


def _user() -> User:
    return User(
        id=uuid4(),
        email="traveler@example.com",
        email_normalized="traveler@example.com",
        password_hash="not-returned",
    )


@pytest.fixture
def anyio_backend() -> str:
    """Use asyncio because the project does not install Trio."""

    return "asyncio"


@pytest.mark.anyio
async def test_conversation_routes_are_documented_and_never_expose_thread_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    service = ConversationCRUDStub(object(), user.id)
    app = create_app()

    async def current_user_override() -> User:
        return user

    async def session_override() -> object:
        return object()

    async def rate_limit_override() -> None:
        return None

    monkeypatch.setattr(conversations_api, "ConversationCRUD", lambda *_: service)
    monkeypatch.setattr(
        conversations_api,
        "MessageCRUD",
        lambda *_: MessageCRUDStub(service.messages),
    )
    app.dependency_overrides[get_current_user] = current_user_override
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[limit_conversation_write] = rate_limit_override
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        created = await client.post("/api/v1/conversations", json={"title": "广州周末"})
        detail = await client.get(f"/api/v1/conversations/{service.conversation.id}")
        listed = await client.get("/api/v1/conversations")
        messages = await client.get(f"/api/v1/conversations/{service.conversation.id}/messages")
        deleted = await client.delete(f"/api/v1/conversations/{service.conversation.id}")

    assert created.status_code == 201
    assert created.json()["title"] == "广州周末"
    assert "thread_id" not in created.json()
    assert detail.status_code == 200
    assert detail.json()["messages"]["data"][0]["rendered_text"] == "你好"
    assert listed.status_code == 200
    assert messages.status_code == 200
    assert deleted.status_code == 204
    paths = app.openapi()["paths"]
    assert "/api/v1/conversations" in paths
    assert "/api/v1/conversations/{conversation_id}/messages" in paths


@pytest.mark.anyio
async def test_conversation_request_validation_uses_the_shared_safe_error_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()
    user = _user()
    service = ConversationCRUDStub(object(), user.id)

    async def current_user_override() -> User:
        return user

    async def session_override() -> object:
        return object()

    async def rate_limit_override() -> None:
        return None

    monkeypatch.setattr(conversations_api, "ConversationCRUD", lambda *_: service)
    monkeypatch.setattr(
        conversations_api,
        "MessageCRUD",
        lambda *_: MessageCRUDStub(service.messages),
    )
    app.dependency_overrides[get_current_user] = current_user_override
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[limit_conversation_write] = rate_limit_override
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/api/v1/conversations", json={"title": "   "})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert response.json()["message"] == "The request is invalid."
    assert response.json()["request_id"]
    assert response.headers["X-Request-ID"] == response.json()["request_id"]


@pytest.mark.anyio
async def test_message_submission_requires_idempotency_and_returns_a_durable_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()
    user = _user()
    service = ConversationCRUDStub(object(), user.id)

    async def current_user_override() -> User:
        return user

    async def session_override() -> object:
        return object()

    async def rate_limit_override() -> None:
        return None

    monkeypatch.setattr(conversations_api, "ConversationCRUD", lambda *_: service)
    app.dependency_overrides[get_current_user] = current_user_override
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[limit_conversation_write] = rate_limit_override

    async def execution_service_override() -> ExecutionServiceStub:
        return ExecutionServiceStub()

    async def idempotency_service_override() -> IdempotencyServiceStub:
        return IdempotencyServiceStub()

    app.dependency_overrides[get_conversation_execution_service] = execution_service_override
    app.dependency_overrides[get_idempotency_service] = idempotency_service_override
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    path = f"/api/v1/conversations/{service.conversation.id}/messages"
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        missing_key = await client.post(path, json={"content": "你好"})
        accepted = await client.post(
            path,
            json={"content": "你好"},
            headers={"Idempotency-Key": "message-001"},
        )

    assert missing_key.status_code == 400
    assert missing_key.json()["code"] == "missing_idempotency_key"
    assert accepted.status_code == 200
    assert accepted.json()["conversation_id"] == str(service.conversation.id)
    assert accepted.json()["message"]["rendered_text"] == "回复：你好"
    assert "post" in app.openapi()["paths"]["/api/v1/conversations/{conversation_id}/messages"]
