"""FastAPI application entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.database import (
    check_database_connection,
    create_database_engine,
    ensure_database_exists,
)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """Create, verify, and dispose of the PostgreSQL connection pool."""

    settings: Settings = application.state.settings
    ensure_database_exists(settings)
    engine = create_database_engine(settings)
    try:
        check_database_connection(engine)
    except SQLAlchemyError:
        engine.dispose()
        raise

    application.state.database_engine = engine
    try:
        yield
    finally:
        engine.dispose()


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
    application.include_router(api_router)
    return application


app = create_app()


def run() -> None:
    """Run the development server for the installed console command."""

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.app_debug)


if __name__ == "__main__":
    run()
