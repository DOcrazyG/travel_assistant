"""Valkey-backed limits with an explicit development-only in-memory fallback."""

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Protocol

from redis.asyncio import Redis

from app.core.config import Settings
from app.core.errors import APIError


class RateLimiter(Protocol):
    """The small interface required by authentication services."""

    async def check(self, key: str, *, limit: int, window_seconds: int) -> None: ...

    async def close(self) -> None: ...


class InMemoryRateLimiter:
    """Process-local limiter permitted only for development and tests."""

    def __init__(self) -> None:
        self._values: dict[str, tuple[int, float]] = {}
        self._lock = asyncio.Lock()

    async def check(self, key: str, *, limit: int, window_seconds: int) -> None:
        async with self._lock:
            count, expires_at = self._values.get(key, (0, monotonic() + window_seconds))
            if monotonic() >= expires_at:
                count, expires_at = 0, monotonic() + window_seconds
            count += 1
            self._values[key] = (count, expires_at)
            if count > limit:
                raise APIError(429, "rate_limited", "Too many requests. Please try again later.")

    async def close(self) -> None:
        return None


@dataclass
class ValkeyRateLimiter:
    """A fixed-window distributed limiter implemented with Valkey counters."""

    client: Redis

    async def check(self, key: str, *, limit: int, window_seconds: int) -> None:
        counter_key = f"rate-limit:{key}"
        count = await self.client.incr(counter_key)
        if count == 1:
            await self.client.expire(counter_key, window_seconds)
        if count > limit:
            raise APIError(429, "rate_limited", "Too many requests. Please try again later.")

    async def close(self) -> None:
        await self.client.aclose()


async def create_rate_limiter(settings: Settings) -> RateLimiter:
    """Connect to Valkey or use the configured local fallback."""

    if settings.redis_url:
        password = (
            settings.valkey_password.get_secret_value()
            if settings.valkey_password is not None
            else None
        )
        client = Redis.from_url(
            settings.redis_url,
            username=settings.valkey_username,
            password=password,
            decode_responses=False,
        )
        try:
            await client.ping()
        except Exception:
            await client.aclose()
            if not settings.effective_allow_in_memory_rate_limit:
                raise
        else:
            return ValkeyRateLimiter(client)
    if settings.effective_allow_in_memory_rate_limit:
        return InMemoryRateLimiter()
    raise RuntimeError("Valkey is unavailable and in-memory rate limiting is disabled")
