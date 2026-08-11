"""Safe API errors that share one application response shape."""

from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
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


def _error_body(
    request: Request,
    *,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the consistent client-safe error envelope used by all API failures."""

    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": str(getattr(request.state, "request_id", "")),
    }
    if details:
        body["details"] = details
    return body


async def validation_error_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    """Return validation errors without reflecting submitted values such as passwords."""

    details = {
        "errors": [
            {"location": list(item["loc"]), "message": item["msg"], "type": item["type"]}
            for item in error.errors()
        ]
    }
    return JSONResponse(
        status_code=422,
        content=_error_body(
            request,
            code="validation_error",
            message="The request is invalid.",
            details=details,
        ),
    )


async def http_error_handler(request: Request, error: HTTPException) -> JSONResponse:
    """Normalize framework-generated errors such as missing paths and methods."""

    message = (
        error.detail if isinstance(error.detail, str) else "The request could not be completed."
    )
    return JSONResponse(
        status_code=error.status_code,
        content=_error_body(request, code="http_error", message=message),
        headers=error.headers,
    )
