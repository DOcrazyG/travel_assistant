"""Health and readiness endpoints."""

from fastapi import APIRouter, status
from pydantic import BaseModel

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    """Minimal health response suitable for container probes."""

    status: str = "ok"


@router.get("/live", response_model=HealthResponse, status_code=status.HTTP_200_OK)
def liveness() -> HealthResponse:
    """Report whether the application process is running."""

    return HealthResponse()


@router.get("/ready", response_model=HealthResponse, status_code=status.HTTP_200_OK)
def readiness() -> HealthResponse:
    """Report whether currently configured startup dependencies are ready.

    Database and cache checks will be added when those dependencies are introduced in P1.
    """

    return HealthResponse()
