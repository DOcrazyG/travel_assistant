"""Integration-style tests for request correlation and safe unexpected errors."""

import json
import logging
from uuid import UUID

import httpx
import pytest
from fastapi import Request

from app.core.config import Settings
from app.core.logging import get_context
from app.main import create_app


def _test_settings() -> Settings:
    """Avoid inheriting a developer's local logging configuration."""

    return Settings(_env_file=None, environment="test", log_format="json")  # type: ignore[call-arg]


@pytest.fixture
def anyio_backend() -> str:
    """Use asyncio because the project does not install Trio."""

    return "asyncio"


@pytest.mark.anyio
async def test_middleware_adds_a_request_id_logs_completion_and_clears_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(_test_settings())

    @app.get("/_test/request-context")
    async def request_context(request: Request) -> dict[str, str]:
        return {"request_id": str(request.state.request_id)}

    caplog.set_level(logging.INFO, logger="app.core.middleware")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/_test/request-context")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == response.json()["request_id"]
    assert UUID(response.headers["X-Request-ID"])
    assert get_context() == {}
    completion = next(
        json.loads(record.getMessage())
        for record in caplog.records
        if '"event": "http_request_completed"' in record.getMessage()
    )
    assert completion["request_id"] == response.headers["X-Request-ID"]
    assert completion["status_code"] == 200


@pytest.mark.anyio
async def test_unexpected_exception_is_safe_and_keeps_the_request_id() -> None:
    app = create_app(_test_settings())

    @app.get("/_test/boom")
    async def boom() -> None:
        raise RuntimeError("provider credential should never reach a client")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/_test/boom")

    assert response.status_code == 500
    assert response.json() == {
        "code": "internal_error",
        "message": "An unexpected error occurred.",
        "request_id": response.headers["X-Request-ID"],
    }
