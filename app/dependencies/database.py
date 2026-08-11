"""Request-scoped database dependency providers."""

from collections.abc import AsyncGenerator

from fastapi import Request
from sqlmodel.ext.asyncio.session import AsyncSession


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield one uncommitted session; services own their transaction boundaries."""

    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session
