"""Tests for password, token, and privacy-preserving security primitives."""

from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.errors import APIError
from app.core.security import (
    decode_access_token,
    hash_identifier,
    hash_password,
    hash_refresh_token,
    issue_access_token,
    new_refresh_token,
    verify_password,
)


def test_password_hashes_are_argon2id_and_verify() -> None:
    password_hash = hash_password("correct horse battery staple")

    valid, upgraded = verify_password("correct horse battery staple", password_hash)

    assert password_hash.startswith("$argon2id$")
    assert valid
    assert upgraded is None


def test_access_token_round_trip_and_tamper_rejection() -> None:
    settings = Settings(jwt_secret_key="x" * 32)
    user_id = uuid4()
    token, token_id, expires_at = issue_access_token(user_id, settings)

    assert decode_access_token(token, settings) == (user_id, token_id, expires_at)

    with pytest.raises(APIError, match="invalid_access_token"):
        decode_access_token(f"{token}tampered", settings)


def test_refresh_tokens_and_audit_identifiers_are_not_stored_as_plaintext() -> None:
    settings = Settings(pii_hash_key="y" * 32)
    token = new_refresh_token()

    assert hash_refresh_token(token) != token.encode("utf-8")
    assert hash_identifier("203.0.113.4", settings) == hash_identifier("203.0.113.4", settings)
    assert hash_identifier("203.0.113.4", settings) != hash_identifier("203.0.113.5", settings)
