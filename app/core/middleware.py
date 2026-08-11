"""HTTP middleware for request correlation, logging context, and safe failures."""

from time import perf_counter
from uuid import UUID

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.errors import unexpected_error_handler
from app.core.logging import bind_context, clear_context, get_logger, reset_context
from app.models.base import new_uuid7

logger = get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Create one server-owned request ID and return it on every response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Attach the correlation identifier before dispatching the request."""

        request_id: UUID = new_uuid7()
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request_id)
        return response


class LoggingContextMiddleware(BaseHTTPMiddleware):
    """Bind request context, emit completion logs, and safely handle unexpected errors."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Create isolated log context for exactly one request."""

        context_token = clear_context()
        request_id = getattr(request.state, "request_id", None)
        if request_id is not None:
            bind_context(request_id=str(request_id))
        started_at = perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception as error:
                response = await unexpected_error_handler(request, error)
            logger.info(
                "http_request_completed",
                http_method=request.method,
                http_path=request.url.path,
                status_code=response.status_code,
                duration_ms=round((perf_counter() - started_at) * 1000, 2),
                user_id=getattr(request.state, "user_id", None),
                conversation_id=str(getattr(request.state, "conversation_id", "")) or None,
            )
            return response
        finally:
            reset_context(context_token)
