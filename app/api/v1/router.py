"""Version 1 route export.

The first baseline route is intentionally exported directly. Additional v1 routers
will be composed here once the FastAPI router stack is introduced in P1.
"""

from app.api.v1.health import router as health_router

api_router = health_router
