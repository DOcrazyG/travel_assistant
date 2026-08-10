"""PostgreSQL engine creation and connectivity checks."""

from sqlalchemy import URL, text
from sqlalchemy.engine import Engine
from sqlmodel import create_engine

from app.core.config import Settings


def create_database_url(settings: Settings, database: str | None = None) -> URL:
    """Build a PostgreSQL URL for an application or maintenance database."""

    return URL.create(
        "postgresql+psycopg",
        username=settings.postgres_user,
        password=settings.postgres_password,
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=database or settings.postgres_database,
    )


def ensure_database_exists(settings: Settings) -> None:
    """Create the configured application database when the PostgreSQL role permits it."""

    maintenance_engine = create_engine(
        create_database_url(settings, settings.postgres_admin_database),
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    try:
        with maintenance_engine.connect() as connection:
            database_exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
                {"database_name": settings.postgres_database},
            ).scalar_one_or_none()
            if database_exists is None:
                quoted_name = maintenance_engine.dialect.identifier_preparer.quote(
                    settings.postgres_database
                )
                connection.execute(text(f"CREATE DATABASE {quoted_name}"))
    finally:
        maintenance_engine.dispose()


def create_database_engine(settings: Settings) -> Engine:
    """Create the PostgreSQL pool used by system-management services."""

    return create_engine(
        create_database_url(settings),
        echo=settings.postgres_echo,
        pool_pre_ping=True,
        pool_size=settings.postgres_pool_size,
        max_overflow=settings.postgres_max_overflow,
    )


def check_database_connection(engine: Engine) -> None:
    """Raise if the database cannot accept a simple connection."""

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
