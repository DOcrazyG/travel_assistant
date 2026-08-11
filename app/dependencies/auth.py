"""Bearer-token and current-user dependencies for protected endpoints."""

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import APIError
from app.dependencies.services import get_auth_service
from app.models.users import User
from app.services.auth import AuthService

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> User:
    """Require a valid bearer token for the endpoint using this dependency."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise APIError(401, "invalid_access_token", "Authentication credentials are required.")
    return await service.current_user(credentials.credentials)
