"""Tests for the explicit development-only in-memory rate limiter."""

import asyncio

import pytest

from app.core.errors import APIError
from app.core.rate_limit import InMemoryRateLimiter


def test_in_memory_limiter_rejects_the_request_after_its_limit() -> None:
    limiter = InMemoryRateLimiter()

    async def check_limit() -> None:
        await limiter.check("login:example", limit=2, window_seconds=60)
        await limiter.check("login:example", limit=2, window_seconds=60)
        with pytest.raises(APIError) as error:
            await limiter.check("login:example", limit=2, window_seconds=60)
        assert error.value.status_code == 429
        assert error.value.code == "rate_limited"

    asyncio.run(check_limit())
