"""Unit tests for durable user-scoped idempotency lifecycle behavior."""

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from app.core.errors import APIError
from app.models.base import utc_now
from app.models.operations import IdempotencyKey
from app.services.idempotency import IdempotencyService, request_fingerprint


class FakeResult:
    def __init__(self, record: IdempotencyKey | None) -> None:
        self.record = record

    def one_or_none(self) -> IdempotencyKey | None:
        return self.record


class FakeSession:
    def __init__(self, record: IdempotencyKey | None = None) -> None:
        self.record = record
        self.added: list[IdempotencyKey] = []
        self.deleted: list[IdempotencyKey] = []
        self.commits = 0

    async def exec(self, _: object) -> FakeResult:
        return FakeResult(self.record)

    def add(self, record: IdempotencyKey) -> None:
        self.added.append(record)

    async def delete(self, record: IdempotencyKey) -> None:
        self.deleted.append(record)

    async def commit(self) -> None:
        self.commits += 1


def service_for(session: FakeSession) -> IdempotencyService:
    return IdempotencyService(session)  # type: ignore[arg-type]


def begin(service: IdempotencyService, user_id: UUID, payload: object) -> object:
    return asyncio.run(
        service.begin(
            user_id=user_id,
            http_method="POST",
            route="/v1/chat/completions",
            idempotency_key="message-1",
            payload=payload,
        )
    )


def test_request_fingerprint_is_stable_for_equivalent_json_objects() -> None:
    assert request_fingerprint({"b": 1, "a": ["x"]}) == request_fingerprint({"a": ["x"], "b": 1})


def test_begin_creates_a_user_scoped_processing_reservation() -> None:
    user_id = uuid4()
    session = FakeSession()

    reservation = begin(service_for(session), user_id, {"message": "你好"})

    assert reservation.replay is False  # type: ignore[union-attr]
    assert reservation.record.user_id == user_id  # type: ignore[union-attr]
    assert reservation.record.status == "processing"  # type: ignore[union-attr]
    assert session.added == [reservation.record]  # type: ignore[union-attr]
    assert session.commits == 1


def test_completed_record_replays_only_the_same_user_and_request() -> None:
    user_id = uuid4()
    record = IdempotencyKey(
        user_id=user_id,
        http_method="POST",
        route="/v1/chat/completions",
        idempotency_key="message-1",
        request_fingerprint=request_fingerprint({"message": "你好"}),
        status="completed",
        response_status=200,
        response_snapshot={"id": "run_1"},
        expires_at=utc_now() + timedelta(hours=1),
    )

    reservation = begin(service_for(FakeSession(record)), user_id, {"message": "你好"})

    assert reservation.replay is True  # type: ignore[union-attr]
    assert reservation.record is record  # type: ignore[union-attr]


def test_reusing_a_key_with_a_different_request_is_rejected() -> None:
    user_id = uuid4()
    record = IdempotencyKey(
        user_id=user_id,
        http_method="POST",
        route="/v1/chat/completions",
        idempotency_key="message-1",
        request_fingerprint=request_fingerprint({"message": "first"}),
        expires_at=utc_now() + timedelta(hours=1),
    )

    with pytest.raises(APIError, match="different request") as error:
        begin(service_for(FakeSession(record)), user_id, {"message": "second"})

    assert error.value.code == "idempotency_key_reused"


def test_processing_record_is_not_executed_twice() -> None:
    user_id = uuid4()
    record = IdempotencyKey(
        user_id=user_id,
        http_method="POST",
        route="/v1/chat/completions",
        idempotency_key="message-1",
        request_fingerprint=request_fingerprint({"message": "你好"}),
        expires_at=utc_now() + timedelta(hours=1),
    )

    with pytest.raises(APIError, match="already being processed") as error:
        begin(service_for(FakeSession(record)), user_id, {"message": "你好"})

    assert error.value.code == "idempotency_in_progress"


def test_complete_persists_the_replay_response() -> None:
    record = IdempotencyKey(
        user_id=uuid4(),
        http_method="POST",
        route="/v1/chat/completions",
        idempotency_key="message-1",
        request_fingerprint=request_fingerprint({"message": "你好"}),
        expires_at=utc_now() + timedelta(hours=1),
    )
    session = FakeSession()

    completed = asyncio.run(
        service_for(session).complete(
            record,
            response_status=202,
            response_snapshot={"run_id": "run_1"},
        )
    )

    assert completed.status == "completed"
    assert completed.response_status == 202
    assert completed.response_snapshot == {"run_id": "run_1"}
    assert completed.completed_at is not None
    assert session.commits == 1
