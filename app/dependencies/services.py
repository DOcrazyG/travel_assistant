"""Factories for application services used by FastAPI route handlers."""

from typing import Annotated

from fastapi import Depends, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from app.dependencies.database import get_session
from app.services.auth import AuthService


def get_auth_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthService:
    """Create an authentication service with request-scoped dependencies."""

    return AuthService(session, request.app.state.settings, request.app.state.rate_limiter)
