"""Tests for fail-fast production authentication configuration."""

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings


def settings_without_dotenv(**values: object) -> Settings:
    """Keep security-setting tests independent from a developer's local .env file."""

    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_production_auth_settings_require_real_secrets_cors_and_valkey() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        settings_without_dotenv(environment="production")


def test_production_auth_settings_accept_explicit_secure_values() -> None:
    settings = settings_without_dotenv(
        environment="production",
        jwt_secret_key="x" * 32,
        pii_hash_key="y" * 32,
        cors_allowed_origins="https://app.example.com, https://admin.example.com/",
        redis_url="redis://valkey:6379/0",
        valkey_password=SecretStr("z" * 32),
        refresh_cookie_secure=True,
    )

    assert settings.effective_refresh_cookie_secure
    assert settings.parsed_cors_allowed_origins == (
        "https://app.example.com",
        "https://admin.example.com",
    )


def test_valkey_connection_requires_a_password() -> None:
    with pytest.raises(ValidationError, match="VALKEY_PASSWORD"):
        settings_without_dotenv(
            environment="production",
            jwt_secret_key="x" * 32,
            pii_hash_key="y" * 32,
            cors_allowed_origins="https://app.example.com",
            redis_url="redis://127.0.0.1:6379/0",
            refresh_cookie_secure=True,
        )
