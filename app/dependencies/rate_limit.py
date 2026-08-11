"""Route dependencies that apply policy-owned distributed rate limits."""

from typing import Annotated

from fastapi import Depends, Request

from app.core.security import identifier_key
from app.dependencies.auth import get_current_user
from app.models.users import User


async def limit_conversation_write(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Limit conversation-management mutations by the authenticated user."""

    settings = request.app.state.settings
    limiter = request.app.state.rate_limiter
    user_key = identifier_key(str(current_user.id), settings)
    await limiter.check(
        f"conversation-write:user:{user_key}",
        limit=settings.conversation_write_rate_limit,
        window_seconds=settings.conversation_write_rate_limit_window_seconds,
    )
