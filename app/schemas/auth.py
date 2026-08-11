"""Request and response schemas for local-account authentication."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, SecretStr, field_validator

from app.schemas.users import UserRead, _normalize_email


class LoginRequest(BaseModel):
    """Credentials accepted by the password-login endpoint."""

    model_config = ConfigDict(extra="forbid")

    email: str
    password: SecretStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Match registration's case-insensitive email lookup."""

        return _normalize_email(value)


class AccessTokenResponse(BaseModel):
    """A short-lived bearer token and the authenticated account."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserRead
