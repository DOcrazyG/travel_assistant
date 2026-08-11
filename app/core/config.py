"""Typed application configuration loaded from the environment."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
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
    log_format: Literal["console", "json"] | None = Field(
        default=None,
        description="Log renderer override; console locally and JSON in deployed environments.",
    )
    conversation_write_rate_limit: int = Field(
        default=30,
        ge=1,
        le=1_000,
        description="Maximum conversation-management writes per user in one window.",
    )
    conversation_write_rate_limit_window_seconds: int = Field(
        default=60,
        ge=1,
        le=3_600,
        description="Window for conversation-management write rate limits.",
    )
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
    jwt_secret_key: str = Field(
        default="development-only-secret-change-before-production",
        min_length=32,
        description="HS256 signing key for access JWTs.",
    )
    jwt_issuer: str = Field(default="travel-assistant", min_length=1)
    jwt_audience: str = Field(default="travel-assistant-api", min_length=1)
    access_token_minutes: int = Field(default=15, ge=1, le=60)
    refresh_session_days: int = Field(default=30, ge=1, le=90)
    max_active_auth_sessions: int = Field(default=5, ge=1, le=20)
    refresh_cookie_name: str = Field(default="travel_assistant_refresh", min_length=1)
    refresh_cookie_secure: bool | None = Field(default=None)
    cors_allowed_origins: str = Field(
        default="",
        description="Comma-separated browser origins allowed to send credentialed requests.",
    )
    redis_url: str | None = Field(default=None)
    valkey_username: str | None = Field(default=None)
    valkey_password: SecretStr | None = Field(default=None)
    allow_in_memory_rate_limit: bool | None = Field(default=None)
    bootstrap_admin_email: str | None = Field(default=None)
    bootstrap_admin_password: SecretStr | None = Field(default=None)
    pii_hash_key: str = Field(
        default="development-only-pii-hash-key-change-before-production",
        min_length=32,
        description="Key used to pseudonymize IP addresses in audit and rate-limit data.",
    )

    @property
    def parsed_cors_allowed_origins(self) -> tuple[str, ...]:
        """Return normalized, explicitly configured CORS origins."""

        return tuple(
            origin.strip().rstrip("/")
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        )

    @property
    def effective_refresh_cookie_secure(self) -> bool:
        """Use secure cookies outside local development unless explicitly overridden."""

        if self.refresh_cookie_secure is not None:
            return self.refresh_cookie_secure
        return self.environment not in {"development", "test"}

    @property
    def effective_allow_in_memory_rate_limit(self) -> bool:
        """Allow the non-distributed limiter only in development or tests by default."""

        if self.allow_in_memory_rate_limit is not None:
            return self.allow_in_memory_rate_limit
        return self.environment in {"development", "test"}

    @property
    def effective_log_format(self) -> Literal["console", "json"]:
        """Use readable local logs and machine-readable logs outside local environments."""

        if self.log_format is not None:
            return self.log_format
        return "console" if self.environment in {"development", "test"} else "json"

    @model_validator(mode="after")
    def validate_production_security_settings(self) -> "Settings":
        """Fail fast when production would start with unsafe auth defaults."""

        if self.environment in {"staging", "production"}:
            if self.jwt_secret_key.startswith("development-only-"):
                raise ValueError("JWT_SECRET_KEY must be configured outside development")
            if self.pii_hash_key.startswith("development-only-"):
                raise ValueError("PII_HASH_KEY must be configured outside development")
            if not self.effective_refresh_cookie_secure:
                raise ValueError("REFRESH_COOKIE_SECURE must be enabled outside development")
            if not self.parsed_cors_allowed_origins:
                raise ValueError("CORS_ALLOWED_ORIGINS must be configured outside development")
            if not self.redis_url:
                raise ValueError("REDIS_URL is required outside development")
            if self.valkey_password is None:
                raise ValueError("VALKEY_PASSWORD is required when REDIS_URL is configured")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached settings for application startup."""

    return Settings()
