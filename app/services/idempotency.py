"""Durable, user-scoped idempotency records for future mutation endpoints."""

import json
from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import APIError
from app.models.base import utc_now
from app.models.operations import IdempotencyKey


@dataclass(frozen=True)
class IdempotencyReservation:
    """A new request reservation or the durable result of an earlier request."""

    record: IdempotencyKey
    replay: bool


def request_fingerprint(payload: Any) -> bytes:
    """Create a stable digest without persisting the request body itself."""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).digest()


class IdempotencyService:
    """Own the idempotency lifecycle for one mutation and one authenticated user."""

    def __init__(self, session: AsyncSession, *, retention_hours: int = 24) -> None:
        self.session = session
        self.retention_hours = retention_hours

    async def begin(
        self,
        *,
        user_id: UUID,
        http_method: str,
        route: str,
        idempotency_key: str,
        payload: Any,
    ) -> IdempotencyReservation:
        """Reserve a request or return its stored terminal response for a safe replay."""

        normalized_key = idempotency_key.strip()
        if not normalized_key or len(normalized_key) > 255:
            raise APIError(400, "invalid_idempotency_key", "Idempotency-Key is invalid.")
        fingerprint = request_fingerprint(payload)
        existing = await self._existing(user_id, http_method, route, normalized_key)
        now = utc_now()
        if existing is not None:
            if existing.expires_at <= now:
                await self.session.delete(existing)
                await self.session.commit()
            else:
                return self._reservation_for_existing(existing, fingerprint)

        record = IdempotencyKey(
            user_id=user_id,
            http_method=http_method.upper(),
            route=route,
            idempotency_key=normalized_key,
            request_fingerprint=fingerprint,
            expires_at=now + timedelta(hours=self.retention_hours),
        )
        self.session.add(record)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            concurrent_record = await self._existing(user_id, http_method, route, normalized_key)
            if concurrent_record is None:
                raise
            return self._reservation_for_existing(concurrent_record, fingerprint)
        return IdempotencyReservation(record=record, replay=False)

    async def complete(
        self,
        record: IdempotencyKey,
        *,
        response_status: int,
        response_snapshot: dict[str, Any],
        conversation_id: UUID | None = None,
        agent_run_id: UUID | None = None,
    ) -> IdempotencyKey:
        """Persist the safe terminal response that should be returned to a replay."""

        record.status = "completed"
        record.response_status = response_status
        record.response_snapshot = response_snapshot
        record.conversation_id = conversation_id
        record.agent_run_id = agent_run_id
        record.completed_at = utc_now()
        await self.session.commit()
        return record

    async def fail(
        self,
        record: IdempotencyKey,
        *,
        response_status: int,
        response_snapshot: dict[str, Any],
    ) -> IdempotencyKey:
        """Persist a safe terminal failure so a retry receives the same result."""

        record.status = "failed"
        record.response_status = response_status
        record.response_snapshot = response_snapshot
        record.completed_at = utc_now()
        await self.session.commit()
        return record

    async def _existing(
        self,
        user_id: UUID,
        http_method: str,
        route: str,
        idempotency_key: str,
    ) -> IdempotencyKey | None:
        result = await self.session.exec(
            select(IdempotencyKey)
            .where(
                IdempotencyKey.user_id == user_id,
                IdempotencyKey.http_method == http_method.upper(),
                IdempotencyKey.route == route,
                IdempotencyKey.idempotency_key == idempotency_key,
            )
            .with_for_update()
        )
        return result.one_or_none()

    @staticmethod
    def _reservation_for_existing(
        record: IdempotencyKey,
        fingerprint: bytes,
    ) -> IdempotencyReservation:
        if record.request_fingerprint != fingerprint:
            raise APIError(
                409,
                "idempotency_key_reused",
                "Idempotency-Key was already used with a different request.",
            )
        if record.status == "processing":
            raise APIError(
                409,
                "idempotency_in_progress",
                "A request with this Idempotency-Key is already being processed.",
            )
        if record.response_status is None or record.response_snapshot is None:
            raise APIError(
                409, "idempotency_unavailable", "The stored request result is unavailable."
            )
        return IdempotencyReservation(record=record, replay=True)
