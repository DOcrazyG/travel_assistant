"""Providers that adapt HTTP request metadata to domain request context."""

from uuid import UUID

from fastapi import Request

from app.services.auth import AuthRequestContext


def get_auth_request_context(request: Request) -> AuthRequestContext:
    """Map framework request metadata to the narrow context persisted by auth."""

    request_id = getattr(request.state, "request_id", None)
    return AuthRequestContext(
        request_id=request_id if isinstance(request_id, UUID) else None,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
