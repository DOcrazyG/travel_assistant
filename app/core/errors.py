"""Safe API errors that share one application response shape."""

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class APIError(Exception):
    """An expected error with a client-safe status, code, and message."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


async def api_error_handler(request: Request, error: Exception) -> JSONResponse:
    """Render an expected error without exposing implementation details."""

    if not isinstance(error, APIError):
        raise error

    body: dict[str, Any] = {
        "code": error.code,
        "message": error.message,
        "request_id": str(getattr(request.state, "request_id", "")),
    }
    if error.details:
        body["details"] = error.details
    return JSONResponse(status_code=error.status_code, content=body)
