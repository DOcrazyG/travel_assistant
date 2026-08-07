"""Typed application configuration loaded from the environment."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings shared by the FastAPI application and future Agent services."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "travel-assistant"
    environment: Literal["development", "test", "staging", "production"] = "development"
    app_debug: bool = False
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = 8000
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_database: str = "travel_assistant"
    mysql_user: str = "travel_assistant"
    mysql_password: str = "travel_assistant"
    mysql_pool_size: int = 5
    mysql_max_overflow: int = 10
    mysql_echo: bool = False


@lru_cache
def get_settings() -> Settings:
    """Return cached settings for application startup."""

    return Settings()
