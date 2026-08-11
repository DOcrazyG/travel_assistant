"""Version 1 route export.

The first baseline route is intentionally exported directly. Additional v1 routers
will be composed here once the FastAPI router stack is introduced in P1.
"""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router, prefix="/api/v1")
api_router.include_router(conversations_router, prefix="/api/v1")
