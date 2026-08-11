"""HTTP endpoints for local-account authentication."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.core.errors import APIError
from app.dependencies.auth import get_current_user
from app.dependencies.request import get_auth_request_context
from app.dependencies.services import get_auth_service
from app.schemas.auth import AccessTokenResponse, LoginRequest
from app.schemas.users import UserCreate, UserRead
from app.services.auth import AuthService, AuthTokens

router = APIRouter(prefix="/auth", tags=["auth"])


def _access_response(tokens: AuthTokens) -> AccessTokenResponse:
    """Convert an issued credential bundle into the documented JSON response."""

    seconds = max(0, int((tokens.access_expires_at - datetime.now(UTC)).total_seconds()))
    return AccessTokenResponse(
        access_token=tokens.access_token,
        expires_in=seconds,
        user=UserRead.model_validate(tokens.user),
    )


def _set_refresh_cookie(response: Response, request: Request, refresh_token: str) -> None:
    """Set the opaque refresh token without exposing it to JavaScript."""

    settings = request.app.state.settings
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=refresh_token,
        max_age=settings.refresh_session_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.effective_refresh_cookie_secure,
        samesite="lax",
        path="/api/v1/auth",
    )


def _require_allowed_origin(request: Request) -> None:
    """Reject cross-origin cookie use unless the origin is explicitly allowlisted."""

    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in request.app.state.settings.parsed_cors_allowed_origins:
        raise APIError(403, "origin_not_allowed", "The request origin is not allowed.")


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserCreate,
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserRead:
    """Create a local account; authentication is a separate explicit login step."""

    user = await service.register(payload, get_auth_request_context(request))
    return UserRead.model_validate(user)


@router.post("/login", response_model=AccessTokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AccessTokenResponse:
    """Issue a bearer access token and an HttpOnly rotating refresh cookie."""

    tokens = await service.login(
        email=payload.email,
        password=payload.password.get_secret_value(),
        context=get_auth_request_context(request),
    )
    _set_refresh_cookie(response, request, tokens.refresh_token)
    return _access_response(tokens)


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AccessTokenResponse:
    """Rotate the refresh cookie and return a new short-lived access token."""

    _require_allowed_origin(request)
    settings = request.app.state.settings
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if not refresh_token:
        raise APIError(401, "invalid_refresh_token", "Refresh authentication is invalid.")
    tokens = await service.refresh(refresh_token, get_auth_request_context(request))
    _set_refresh_cookie(response, request, tokens.refresh_token)
    return _access_response(tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    """Clear the browser cookie and revoke any current session and bearer token."""

    _require_allowed_origin(request)
    settings = request.app.state.settings
    authorization = request.headers.get("authorization", "")
    access_token = authorization[7:] if authorization.lower().startswith("bearer ") else None
    await service.logout(
        request.cookies.get(settings.refresh_cookie_name),
        access_token,
        get_auth_request_context(request),
    )
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        httponly=True,
        secure=settings.effective_refresh_cookie_secure,
        samesite="lax",
        path="/api/v1/auth",
    )


@router.get("/me", response_model=UserRead)
async def me(current_user: Annotated[UserRead, Depends(get_current_user)]) -> UserRead:
    """Return the account represented by the caller's access JWT."""

    return UserRead.model_validate(current_user)
