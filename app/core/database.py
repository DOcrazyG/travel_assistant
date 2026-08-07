"""MySQL engine creation and connectivity checks."""

from sqlalchemy import URL, text
from sqlalchemy.engine import Engine
from sqlmodel import create_engine

from app.core.config import Settings


def create_database_engine(settings: Settings) -> Engine:
    """Create the MySQL connection pool used by system-management services."""

    database_url = URL.create(
        "mysql+pymysql",
        username=settings.mysql_user,
        password=settings.mysql_password,
        host=settings.mysql_host,
        port=settings.mysql_port,
        database=settings.mysql_database,
    )
    return create_engine(
        database_url,
        echo=settings.mysql_echo,
        pool_pre_ping=True,
        pool_size=settings.mysql_pool_size,
        max_overflow=settings.mysql_max_overflow,
    )


def check_database_connection(engine: Engine) -> None:
    """Raise if the database cannot accept a simple connection."""

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
