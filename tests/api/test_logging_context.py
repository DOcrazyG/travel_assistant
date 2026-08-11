"""Tests for authentication and conversation fields added to request log context."""

from typing import cast
from uuid import uuid4

import pytest
from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials

from app.api.v1.conversations import _bind_conversation_context
from app.core.config import Settings
from app.core.logging import clear_context, get_context, reset_context
from app.core.security import identifier_key
from app.dependencies.auth import get_current_user
from app.models.conversations import Conversation
from app.models.users import User
from app.services.auth import AuthService


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


@pytest.fixture
def anyio_backend() -> str:
    """Use asyncio because the project does not install Trio."""

    return "asyncio"


@pytest.mark.anyio
async def test_authentication_binds_a_redacted_user_identifier() -> None:
    settings = Settings(_env_file=None, pii_hash_key="x" * 32)  # type: ignore[call-arg]
    user = User(
        id=uuid4(),
        email="traveler@example.com",
        email_normalized="traveler@example.com",
        password_hash="not-returned",
    )

    class AuthServiceStub:
        def __init__(self) -> None:
            self.settings = settings

        async def current_user(self, _: str) -> User:
            return user

    request = _request()
    context_token = clear_context()
    try:
        resolved_user = await get_current_user(
            request,
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="token"),
            cast(AuthService, AuthServiceStub()),
        )

        expected_user_id = identifier_key(str(user.id), settings)[:16]
        assert resolved_user is user
        assert request.state.user_id == expected_user_id
        assert get_context() == {"user_id": expected_user_id}
    finally:
        reset_context(context_token)


def test_owned_conversation_binds_its_public_identifier() -> None:
    conversation = Conversation(user_id=uuid4())
    request = _request()
    context_token = clear_context()
    try:
        _bind_conversation_context(request, conversation)

        assert request.state.conversation_id == conversation.id
        assert get_context() == {"conversation_id": str(conversation.id)}
    finally:
        reset_context(context_token)
