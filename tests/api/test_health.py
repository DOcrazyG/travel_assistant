"""Health endpoint tests."""

from app.api.v1.health import liveness, readiness
from app.main import create_app


def test_liveness_returns_ok() -> None:
    assert liveness().model_dump() == {"status": "ok"}


def test_readiness_returns_ok() -> None:
    assert readiness().model_dump() == {"status": "ok"}


def test_health_routes_are_included_in_openapi() -> None:
    paths = create_app().openapi()["paths"]

    assert "/health/live" in paths
    assert "/health/ready" in paths
