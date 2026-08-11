"""Password, JWT, refresh-token, and privacy-preserving identifier helpers."""

import hmac
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from uuid import UUID

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash

from app.core.config import Settings
from app.core.errors import APIError
from app.models.base import new_uuid7

password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Hash a new password using pwdlib's Argon2id recommendation."""

    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> tuple[bool, str | None]:
    """Verify a password and return an upgraded hash when parameters changed."""

    return password_hasher.verify_and_update(password, password_hash)


def new_refresh_token() -> str:
    """Create a high-entropy opaque token suitable for an HttpOnly cookie."""

    return token_urlsafe(32)


def hash_refresh_token(token: str) -> bytes:
    """Store a one-way digest instead of a usable refresh credential."""

    return sha256(token.encode("utf-8")).digest()


def hash_identifier(value: str | None, settings: Settings) -> bytes | None:
    """Pseudonymize values such as IP addresses before persisting or caching them."""

    if not value:
        return None
    return hmac.digest(settings.pii_hash_key.encode("utf-8"), value.encode("utf-8"), "sha256")


def identifier_key(value: str | None, settings: Settings) -> str:
    """Produce a printable HMAC digest for a Valkey key without leaking the value."""

    return (hash_identifier(value, settings) or b"unknown").hex()


def issue_access_token(user_id: UUID, settings: Settings) -> tuple[str, UUID, datetime]:
    """Issue a short-lived access JWT with the required registered claims."""

    # JWT NumericDate claims have one-second precision, so retain that precision
    # in the returned expiry value as well.
    now = datetime.now(UTC).replace(microsecond=0)
    expires_at = now + timedelta(minutes=settings.access_token_minutes)
    token_id = new_uuid7()
    token = jwt.encode(
        {
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "sub": str(user_id),
            "jti": str(token_id),
            "iat": now,
            "exp": expires_at,
            "typ": "access",
        },
        settings.jwt_secret_key,
        algorithm="HS256",
    )
    return token, token_id, expires_at


def decode_access_token(token: str, settings: Settings) -> tuple[UUID, UUID, datetime]:
    """Validate an access JWT and return its subject, ID, and expiry."""

    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=["HS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "jti", "iss", "aud"]},
        )
        if claims.get("typ") != "access":
            raise InvalidTokenError("unexpected token type")
        return UUID(claims["sub"]), UUID(claims["jti"]), datetime.fromtimestamp(claims["exp"], UTC)
    except (InvalidTokenError, KeyError, TypeError, ValueError) as error:
        raise APIError(
            401, "invalid_access_token", "Authentication credentials are invalid."
        ) from error
