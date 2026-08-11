"""Shared API pagination DTOs."""

from pydantic import BaseModel, Field


class OffsetPage(BaseModel):
    """Bounded offset pagination metadata returned by list endpoints."""

    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    next_offset: int | None = Field(default=None, ge=0)
