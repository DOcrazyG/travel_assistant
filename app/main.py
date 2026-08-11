"""FastAPI application entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast
from uuid import UUID

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ExceptionHandler

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.database import (
    check_database_connection,
    create_database_engine,
    create_session_factory,
    ensure_database_exists,
)
from app.core.errors import (
    APIError,
    api_error_handler,
    http_error_handler,
    validation_error_handler,
)
from app.core.rate_limit import create_rate_limiter
from app.models.base import new_uuid7
from app.services.auth import ensure_bootstrap_admin


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """Create, verify, and dispose of the PostgreSQL connection pool."""

    settings: Settings = application.state.settings
    ensure_database_exists(settings)
    engine = create_database_engine(settings)
    try:
        await check_database_connection(engine)
    except SQLAlchemyError:
        await engine.dispose()
        raise

    application.state.database_engine = engine
    application.state.session_factory = create_session_factory(engine)
    rate_limiter = await create_rate_limiter(settings)
    application.state.rate_limiter = rate_limiter
    try:
        async with application.state.session_factory() as session:
            await ensure_bootstrap_admin(session, settings)
        yield
    finally:
        await rate_limiter.close()
        await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the HTTP application without importing Agent runtime dependencies."""

    active_settings = settings or get_settings()
    application = FastAPI(
        title="Travel Assistant API",
        version="0.1.0",
        debug=active_settings.app_debug,
        lifespan=lifespan,
    )
    application.state.settings = active_settings
    application.add_exception_handler(APIError, api_error_handler)
    application.add_exception_handler(
        RequestValidationError,
        cast(ExceptionHandler, validation_error_handler),
    )
    application.add_exception_handler(HTTPException, cast(ExceptionHandler, http_error_handler))
    if active_settings.parsed_cors_allowed_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(active_settings.parsed_cors_allowed_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @application.middleware("http")
    async def add_request_id(request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Attach a request ID used by errors, audits, and response correlation."""

        request_id: UUID = new_uuid7()
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request_id)
        return response

    application.include_router(api_router)
    return application


app = create_app()


def run() -> None:
    """Run the development server for the installed console command."""

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.app_debug)


if __name__ == "__main__":
    run()
