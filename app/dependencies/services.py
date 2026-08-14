"""Factories for application services used by FastAPI route handlers."""

from typing import Annotated

from fastapi import Depends, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from app.dependencies.database import get_session
from app.services.auth import AuthService
from app.services.conversation_execution import ConversationExecutionService
from app.services.idempotency import IdempotencyService


def get_auth_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthService:
    """Create an authentication service with request-scoped dependencies."""

    return AuthService(session, request.app.state.settings, request.app.state.rate_limiter)


def get_conversation_execution_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConversationExecutionService:
    """Inject the application-owned graph and model into a request-scoped service."""

    return ConversationExecutionService(
        session,
        request.app.state.travel_agent_graph,
        request.app.state.travel_llm,
    )


def get_idempotency_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IdempotencyService:
    """Provide the durable replay boundary for one request session."""

    return IdempotencyService(session)
