"""FastAPI application entry point."""

import uvicorn
from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the HTTP application without importing Agent runtime dependencies."""

    active_settings = settings or get_settings()
    application = FastAPI(
        title="Travel Assistant API",
        version="0.1.0",
        debug=active_settings.debug,
    )
    application.include_router(api_router)
    return application


app = create_app()


def run() -> None:
    """Run the development server for the installed console command."""

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)


if __name__ == "__main__":
    run()
