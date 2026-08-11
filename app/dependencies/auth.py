"""Bearer-token and current-user dependencies for protected endpoints."""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import APIError
from app.core.logging import bind_context
from app.core.security import identifier_key
from app.dependencies.services import get_auth_service
from app.models.users import User
from app.services.auth import AuthService

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> User:
    """Require a valid bearer token for the endpoint using this dependency."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise APIError(401, "invalid_access_token", "Authentication credentials are required.")
    user = await service.current_user(credentials.credentials)
    redacted_user_id = identifier_key(str(user.id), service.settings)[:16]
    request.state.user_id = redacted_user_id
    bind_context(user_id=redacted_user_id)
    return user
