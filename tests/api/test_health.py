"""Health endpoint tests."""

import asyncio

import pytest

from app import main as main_module
from app.api.v1.health import liveness, readiness
from app.core.config import Settings
from app.core.database import create_database_engine
from app.main import create_app


def test_liveness_returns_ok() -> None:
    assert liveness().model_dump() == {"status": "ok"}


def test_readiness_returns_ok() -> None:
    assert readiness().model_dump() == {"status": "ok"}


def test_health_routes_are_included_in_openapi() -> None:
    paths = create_app().openapi()["paths"]

    assert "/health/live" in paths
    assert "/health/ready" in paths


def test_mysql_engine_uses_the_configured_settings() -> None:
    settings = Settings(
        mysql_host="mysql.test",
        mysql_port=3307,
        mysql_database="test_database",
        mysql_user="test_user",
        mysql_password="test_password",
    )
    engine = create_database_engine(settings)

    try:
        assert engine.url.drivername == "mysql+pymysql"
        assert engine.url.host == "mysql.test"
        assert engine.url.port == 3307
        assert engine.url.database == "test_database"
        assert engine.url.username == "test_user"
    finally:
        engine.dispose()


def test_lifespan_verifies_and_disposes_the_database_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeEngine:
        disposed = False

        def dispose(self) -> None:
            self.disposed = True

    engine = FakeEngine()
    connection_checked = False

    def create_engine(_: Settings) -> FakeEngine:
        return engine

    def check_connection(_: FakeEngine) -> None:
        nonlocal connection_checked
        connection_checked = True

    monkeypatch.setattr(main_module, "create_database_engine", create_engine)
    monkeypatch.setattr(main_module, "check_database_connection", check_connection)
    application = create_app(Settings(environment="test"))

    async def manage_lifespan() -> None:
        async with main_module.lifespan(application):
            assert application.state.database_engine is engine
            assert connection_checked
            assert not engine.disposed

    asyncio.run(manage_lifespan())

    assert engine.disposed
