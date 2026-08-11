"""Tests for reusable route-level rate-limit dependencies."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from fastapi import Request

from app.core.config import Settings
from app.core.security import identifier_key
from app.dependencies.rate_limit import limit_conversation_write
from app.models.users import User


class RateLimiterStub:
    def __init__(self) -> None:
        self.checks: list[tuple[str, int, int]] = []

    async def check(self, key: str, *, limit: int, window_seconds: int) -> None:
        self.checks.append((key, limit, window_seconds))


def settings_without_dotenv(**values: object) -> Settings:
    """Keep this policy test independent from a developer's local configuration."""

    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_conversation_write_limit_uses_a_pseudonymous_user_key() -> None:
    settings = settings_without_dotenv(
        pii_hash_key="x" * 32,
        conversation_write_rate_limit=7,
        conversation_write_rate_limit_window_seconds=90,
    )
    limiter = RateLimiterStub()
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/conversations",
            "headers": [],
            "app": SimpleNamespace(state=SimpleNamespace(settings=settings, rate_limiter=limiter)),
        }
    )
    user = User(
        id=uuid4(),
        email="traveler@example.com",
        email_normalized="traveler@example.com",
        password_hash="not-returned",
    )

    asyncio.run(limit_conversation_write(request, user))

    assert limiter.checks == [
        (
            f"conversation-write:user:{identifier_key(str(user.id), settings)}",
            7,
            90,
        )
    ]
