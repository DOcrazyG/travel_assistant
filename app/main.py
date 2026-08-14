"""FastAPI application entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from starlette.types import ExceptionHandler

from app.agent.travel import create_travel_agent_graph
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.database import (
    check_database_connection,
    create_checkpoint_database_url,
    create_database_engine,
    create_session_factory,
    ensure_database_exists,
)
from app.core.errors import (
    APIError,
    api_error_handler,
    http_error_handler,
    unexpected_error_handler,
    validation_error_handler,
)
from app.core.logging import configure_logging
from app.core.middleware import LoggingContextMiddleware, RequestContextMiddleware
from app.core.rate_limit import create_rate_limiter
from app.services.auth import ensure_bootstrap_admin
from app.services.llm import OpenAICompatibleLLM


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """Create, verify, and dispose of API and graph persistence resources."""

    settings: Settings = application.state.settings
    ensure_database_exists(settings)
    engine = create_database_engine(settings)
    rate_limiter = None
    checkpointer_context = None
    try:
        await check_database_connection(engine)
        application.state.database_engine = engine
        application.state.session_factory = create_session_factory(engine)
        rate_limiter = await create_rate_limiter(settings)
        application.state.rate_limiter = rate_limiter
        checkpointer_context = AsyncPostgresSaver.from_conn_string(
            create_checkpoint_database_url(settings)
        )
        checkpointer = await checkpointer_context.__aenter__()
        application.state.travel_agent_graph = create_travel_agent_graph(checkpointer)
        if not hasattr(application.state, "travel_llm"):
            application.state.travel_llm = OpenAICompatibleLLM(settings)
        async with application.state.session_factory() as session:
            await ensure_bootstrap_admin(session, settings)
        yield
    finally:
        if checkpointer_context is not None:
            await checkpointer_context.__aexit__(None, None, None)
        if rate_limiter is not None:
            await rate_limiter.close()
        await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the HTTP application without importing Agent runtime dependencies."""

    active_settings = settings or get_settings()
    configure_logging(active_settings)
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
    application.add_exception_handler(Exception, cast(ExceptionHandler, unexpected_error_handler))
    if active_settings.parsed_cors_allowed_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(active_settings.parsed_cors_allowed_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )

    application.add_middleware(LoggingContextMiddleware)
    application.add_middleware(RequestContextMiddleware)

    application.include_router(api_router)
    return application


app = create_app()


def run() -> None:
    """Run the development server for the installed console command."""

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.app_debug)


if __name__ == "__main__":
    run()
