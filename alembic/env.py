"""Alembic environment for application-owned PostgreSQL tables."""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

import app.models  # noqa: F401  # Register SQLModel tables before reading metadata.
from alembic import context
from app.core.config import Settings
from app.core.database import create_database_url
from app.models.base import APP_SCHEMA

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def database_url() -> str:
    """Build the migration URL from the same typed settings as the application."""

    return create_database_url(Settings()).render_as_string(hide_password=False).replace("%", "%%")


config.set_main_option("sqlalchemy.url", database_url())
target_metadata = SQLModel.metadata


def include_name(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:
    """Restrict autogeneration to the application schema and version-table schema."""

    if type_ == "schema":
        return name in {None, APP_SCHEMA}
    return True


def configure_context(**kwargs: object) -> None:
    """Configure common comparison options for offline and online migrations."""

    context.configure(
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        compare_type=True,
        compare_server_default=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    """Render migrations to SQL without a live database connection."""

    configure_context(
        url=config.get_main_option("sqlalchemy.url"),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations using an isolated connection pool."""

    configuration = config.get_section(config.config_ini_section, {})
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        configure_context(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
