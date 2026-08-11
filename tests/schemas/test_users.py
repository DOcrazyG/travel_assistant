"""Validation coverage for public user CRUD schemas."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from app.schemas.users import UserCreate, UserRead, UserUpdate


def test_user_create_normalizes_email_and_hides_password() -> None:
    user = UserCreate(email="  Traveler@Example.COM ", password=SecretStr("correct horse battery"))

    assert user.email == "traveler@example.com"
    assert str(user.password) == "**********"
    assert user.password.get_secret_value() == "correct horse battery"


@pytest.mark.parametrize("password", ["short", "x" * 65])
def test_user_create_rejects_passwords_outside_the_confirmed_length_policy(
    password: str,
) -> None:
    with pytest.raises(ValidationError, match="between 8 and 64"):
        UserCreate(email="traveler@example.com", password=SecretStr(password))


@pytest.mark.parametrize("email", ["traveler", "@example.com", "traveler@example"])
def test_user_create_rejects_malformed_email(email: str) -> None:
    with pytest.raises(ValidationError, match="valid email address"):
        UserCreate(email=email, password=SecretStr("correct horse battery"))


def test_user_update_requires_a_mutable_field_and_normalizes_an_email() -> None:
    with pytest.raises(ValidationError, match="at least one mutable field"):
        UserUpdate()

    update = UserUpdate(email="New@Example.COM")

    assert update.email == "new@example.com"


def test_user_read_omits_password_and_accepts_orm_attributes() -> None:
    now = datetime.now(UTC)

    user = UserRead.model_validate(
        {
            "id": uuid4(),
            "email": "traveler@example.com",
            "status": "active",
            "is_admin": False,
            "email_verified_at": None,
            "last_login_at": None,
            "created_at": now,
            "updated_at": now,
            "password_hash": "must-not-be-exposed",
        }
    )

    assert "password" not in user.model_dump()
    assert user.is_admin is False
