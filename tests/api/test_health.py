"""Health endpoint tests."""

import asyncio

import pytest

from app import main as main_module
from app.api.v1.health import liveness, readiness
from app.core import database as database_module
from app.core.config import Settings
from app.core.database import create_database_engine, ensure_database_exists
from app.main import create_app


def test_liveness_returns_ok() -> None:
    assert liveness().model_dump() == {"status": "ok"}


def test_readiness_returns_ok() -> None:
    assert readiness().model_dump() == {"status": "ok"}


def test_health_routes_are_included_in_openapi() -> None:
    paths = create_app().openapi()["paths"]

    assert "/health/live" in paths
    assert "/health/ready" in paths


def test_postgres_engine_uses_the_configured_settings() -> None:
    settings = Settings(
        postgres_host="postgres.test",
        postgres_port=5433,
        postgres_database="test_database",
        postgres_user="test_user",
        postgres_password="test_password",
    )
    engine = create_database_engine(settings)

    try:
        assert engine.url.drivername == "postgresql+psycopg"
        assert engine.url.host == "postgres.test"
        assert engine.url.port == 5433
        assert engine.url.database == "test_database"
        assert engine.url.username == "test_user"
    finally:
        engine.dispose()


def test_database_is_created_when_it_does_not_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    statements: list[tuple[str, dict[str, str] | None]] = []

    class FakeResult:
        def scalar_one_or_none(self) -> None:
            return None

    class FakeConnection:
        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def execute(
            self, statement: object, parameters: dict[str, str] | None = None
        ) -> FakeResult:
            statements.append((str(statement), parameters))
            return FakeResult()

    class FakeIdentifierPreparer:
        @staticmethod
        def quote(identifier: str) -> str:
            return f'"{identifier}"'

    class FakeEngine:
        class dialect:
            identifier_preparer = FakeIdentifierPreparer()

        disposed = False

        @staticmethod
        def connect() -> FakeConnection:
            return FakeConnection()

        def dispose(self) -> None:
            self.disposed = True

    engine = FakeEngine()
    engine_options: dict[str, object] = {}

    def create_engine(_: object, **kwargs: object) -> FakeEngine:
        engine_options.update(kwargs)
        return engine

    monkeypatch.setattr(database_module, "create_engine", create_engine)

    ensure_database_exists(Settings(postgres_database="database_to_create"))

    assert engine_options == {"isolation_level": "AUTOCOMMIT", "pool_pre_ping": True}
    assert statements == [
        (
            "SELECT 1 FROM pg_database WHERE datname = :database_name",
            {"database_name": "database_to_create"},
        ),
        ('CREATE DATABASE "database_to_create"', None),
    ]
    assert engine.disposed


def test_lifespan_verifies_and_disposes_the_database_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeEngine:
        disposed = False

        def dispose(self) -> None:
            self.disposed = True

    engine = FakeEngine()
    connection_checked = False
    database_created = False

    def create_engine(_: Settings) -> FakeEngine:
        return engine

    def check_connection(_: FakeEngine) -> None:
        nonlocal connection_checked
        connection_checked = True

    def ensure_database(_: Settings) -> None:
        nonlocal database_created
        database_created = True

    monkeypatch.setattr(main_module, "create_database_engine", create_engine)
    monkeypatch.setattr(main_module, "check_database_connection", check_connection)
    monkeypatch.setattr(main_module, "ensure_database_exists", ensure_database)
    application = create_app(Settings(environment="test"))

    async def manage_lifespan() -> None:
        async with main_module.lifespan(application):
            assert application.state.database_engine is engine
            assert database_created
            assert connection_checked
            assert not engine.disposed

    asyncio.run(manage_lifespan())

    assert engine.disposed
