"""Tests for the startup-only administrator bootstrap operation."""

import asyncio
from typing import Any

from pydantic import SecretStr

from app.core.config import Settings
from app.models.operations import SecurityAuditEvent
from app.models.users import User
from app.services.auth import ensure_bootstrap_admin


class FakeResult:
    def __init__(self, entity: User | None = None) -> None:
        self.entity = entity

    def one_or_none(self) -> User | None:
        return self.entity


class FakeSession:
    def __init__(self, existing_admin: User | None = None) -> None:
        self.existing_admin = existing_admin
        self.added: list[Any] = []
        self.commit_count = 0
        self.rollback_count = 0
        self.flush_count = 0

    async def exec(self, _: object) -> FakeResult:
        return FakeResult(self.existing_admin)

    def add(self, entity: Any) -> None:
        self.added.append(entity)

    async def commit(self) -> None:
        self.commit_count += 1

    async def flush(self) -> None:
        self.flush_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


def test_bootstrap_creates_the_configured_administrator_when_none_exists() -> None:
    session = FakeSession()
    settings = Settings(
        bootstrap_admin_email="admin@example.com",
        bootstrap_admin_password=SecretStr("correct horse battery staple"),
    )

    asyncio.run(ensure_bootstrap_admin(session, settings))  # type: ignore[arg-type]

    administrator = next(entity for entity in session.added if isinstance(entity, User))
    audit_event = next(entity for entity in session.added if isinstance(entity, SecurityAuditEvent))
    assert administrator.email == "admin@example.com"
    assert administrator.is_admin
    assert administrator.password_hash.startswith("$argon2id$")
    assert audit_event.event_type == "auth.bootstrap_admin"
    assert session.flush_count == 1
    assert session.commit_count == 1


def test_bootstrap_keeps_an_existing_administrator_unchanged() -> None:
    session = FakeSession(
        existing_admin=User(
            email="admin@example.com",
            email_normalized="admin@example.com",
            password_hash="hash",
            is_admin=True,
        )
    )
    settings = Settings()

    asyncio.run(ensure_bootstrap_admin(session, settings))  # type: ignore[arg-type]

    assert session.added == []
    assert session.commit_count == 0
