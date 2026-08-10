"""Typed application configuration loaded from the environment."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings shared by the FastAPI application and future Agent services."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="travel-assistant", description="Application display name.")
    environment: Literal["development", "test", "staging", "production"] = Field(
        default="development", description="Deployment environment."
    )
    app_debug: bool = Field(default=False, description="Enable FastAPI debug mode.")
    log_level: str = Field(default="INFO", description="Application log level.")
    host: str = Field(default="127.0.0.1", description="HTTP server bind address.")
    port: int = Field(default=8000, description="HTTP server bind port.")
    postgres_host: str = Field(default="127.0.0.1", description="PostgreSQL server host.")
    postgres_port: int = Field(default=5432, description="PostgreSQL server port.")
    postgres_database: str = Field(
        default="travel_assistant", description="Application PostgreSQL database name."
    )
    postgres_admin_database: str = Field(
        default="postgres",
        description="Maintenance database used to create the application database.",
    )
    postgres_user: str = Field(default="travel_assistant", description="PostgreSQL user name.")
    postgres_password: str = Field(
        default="travel_assistant", description="PostgreSQL user password."
    )
    postgres_pool_size: int = Field(default=5, description="Persistent PostgreSQL pool size.")
    postgres_max_overflow: int = Field(
        default=10, description="Maximum temporary PostgreSQL pool connections."
    )
    postgres_echo: bool = Field(default=False, description="Log PostgreSQL SQL statements.")


@lru_cache
def get_settings() -> Settings:
    """Return cached settings for application startup."""

    return Settings()
