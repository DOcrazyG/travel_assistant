"""PostgreSQL integration-test fixtures with an isolated, disposable database."""

import os
from collections.abc import Generator
from pathlib import Path
from secrets import token_hex

import pytest
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from alembic import command
from app.core.config import Settings
from app.core.database import create_database_url, ensure_database_exists

if os.getenv("RUN_POSTGRES_INTEGRATION") != "1":
    pytest.skip(
        "set RUN_POSTGRES_INTEGRATION=1 to run PostgreSQL integration tests",
        allow_module_level=True,
    )


def _test_database_name() -> str:
    return f"travel_assistant_integration_{token_hex(8)}"


def _drop_test_database(settings: Settings) -> None:
    """Drop only the UUID-suffixed database created by this test session."""

    database_name = settings.postgres_database
    if not database_name.startswith("travel_assistant_integration_"):
        raise RuntimeError("Refusing to drop a database outside the integration-test namespace")
    engine = create_engine(
        create_database_url(settings, settings.postgres_admin_database),
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    try:
        with engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :name"
                ),
                {"name": database_name},
            )
            quoted_name = engine.dialect.identifier_preparer.quote(database_name)
            connection.execute(text(f"DROP DATABASE IF EXISTS {quoted_name}"))
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def integration_settings() -> Settings:
    """Derive local connection settings but isolate all test data in a fresh database."""

    base_settings = Settings()
    return base_settings.model_copy(
        update={
            "environment": "test",
            "postgres_database": _test_database_name(),
            "redis_url": None,
            "allow_in_memory_rate_limit": True,
            "bootstrap_admin_email": "bootstrap@example.test",
            "bootstrap_admin_password": SecretStr("CorrectHorseBatteryStaple!42"),
        }
    )


@pytest.fixture(scope="session", autouse=True)
def migrated_test_database(integration_settings: Settings) -> Generator[None, None, None]:
    """Create, migrate, and reliably remove the dedicated integration database."""

    ensure_database_exists(integration_settings)
    alembic_config = Config(str(Path("alembic.ini")))
    alembic_config.attributes["database_url"] = create_database_url(
        integration_settings
    ).render_as_string(hide_password=False)
    try:
        command.upgrade(alembic_config, "head")
        yield
    finally:
        _drop_test_database(integration_settings)
