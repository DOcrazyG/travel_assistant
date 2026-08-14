"""End-to-end PostgreSQL tests for authenticated conversation API boundaries."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest
from langchain_core.messages import AIMessage, BaseMessage

from app.core.config import Settings
from app.core.errors import APIError
from app.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
def anyio_backend() -> str:
    """Use asyncio because the project does not install Trio."""

    return "asyncio"


@asynccontextmanager
async def api_client(
    settings: Settings,
    *,
    llm: object | None = None,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Run one application lifespan against the migrated integration database."""

    app = create_app(settings)
    if llm is not None:
        app.state.travel_llm = llm
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


async def access_token(client: httpx.AsyncClient) -> str:
    """Register a unique account and return its bearer credential."""

    email = f"traveler-{uuid4().hex}@example.test"
    password = "CorrectHorseBatteryStaple!42"
    registered = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    assert registered.status_code == 201, registered.text
    logged_in = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert logged_in.status_code == 200, logged_in.text
    return str(logged_in.json()["access_token"])


def bearer(token: str) -> dict[str, str]:
    """Build authenticated request headers."""

    return {"Authorization": f"Bearer {token}"}


class FakeLLM:
    """Avoid external provider calls while testing the durable message boundary."""

    def __init__(self) -> None:
        self.calls: list[list[BaseMessage]] = []

    async def ainvoke(self, messages: list[BaseMessage]) -> BaseMessage:
        self.calls.append(messages)
        return AIMessage(content="这是持久化的助手回复。")


class UnavailableLLM:
    """Return an expected provider failure without making a network call."""

    async def ainvoke(self, _: list[BaseMessage]) -> BaseMessage:
        raise APIError(503, "llm_unavailable", "The travel model is temporarily unavailable.")


@pytest.mark.anyio
async def test_missing_credentials_use_the_shared_error_format(
    integration_settings: Settings,
) -> None:
    async with api_client(integration_settings) as client:
        response = await client.get("/api/v1/conversations")

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_access_token"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.anyio
async def test_conversation_data_is_hidden_from_other_users(
    integration_settings: Settings,
) -> None:
    async with api_client(integration_settings) as client:
        owner_token = await access_token(client)
        other_token = await access_token(client)
        created = await client.post(
            "/api/v1/conversations",
            headers=bearer(owner_token),
            json={"title": "Owner only"},
        )
        assert created.status_code == 201, created.text
        conversation_id = created.json()["id"]

        response = await client.get(
            f"/api/v1/conversations/{conversation_id}",
            headers=bearer(other_token),
        )

    assert response.status_code == 404
    assert response.json()["code"] == "conversation_not_found"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.anyio
async def test_owned_conversations_paginate_without_cross_user_records(
    integration_settings: Settings,
) -> None:
    async with api_client(integration_settings) as client:
        owner_token = await access_token(client)
        other_token = await access_token(client)
        for title in ("First", "Second", "Third"):
            created = await client.post(
                "/api/v1/conversations",
                headers=bearer(owner_token),
                json={"title": title},
            )
            assert created.status_code == 201, created.text
        other_created = await client.post(
            "/api/v1/conversations",
            headers=bearer(other_token),
            json={"title": "Other user"},
        )
        assert other_created.status_code == 201, other_created.text

        first_page = await client.get(
            "/api/v1/conversations?offset=0&limit=2",
            headers=bearer(owner_token),
        )
        second_page = await client.get(
            "/api/v1/conversations?offset=2&limit=2",
            headers=bearer(owner_token),
        )

    assert first_page.status_code == 200
    assert len(first_page.json()["data"]) == 2
    assert first_page.json()["page"]["next_offset"] == 2
    assert second_page.status_code == 200
    assert len(second_page.json()["data"]) == 1
    assert second_page.json()["page"]["next_offset"] is None
    assert all(item["title"] != "Other user" for item in first_page.json()["data"])


@pytest.mark.anyio
async def test_conversation_survives_an_application_restart(
    integration_settings: Settings,
) -> None:
    async with api_client(integration_settings) as client:
        token = await access_token(client)
        created = await client.post(
            "/api/v1/conversations",
            headers=bearer(token),
            json={"title": "Persistent conversation"},
        )
        assert created.status_code == 201, created.text
        conversation_id = created.json()["id"]

    async with api_client(integration_settings) as restarted_client:
        response = await restarted_client.get(
            f"/api/v1/conversations/{conversation_id}",
            headers=bearer(token),
        )

    assert response.status_code == 200
    assert response.json()["title"] == "Persistent conversation"


@pytest.mark.anyio
async def test_message_completion_and_history_survive_an_application_restart(
    integration_settings: Settings,
) -> None:
    first_llm = FakeLLM()
    async with api_client(integration_settings, llm=first_llm) as client:
        token = await access_token(client)
        created = await client.post("/api/v1/conversations", headers=bearer(token), json={})
        assert created.status_code == 201, created.text
        conversation_id = created.json()["id"]
        completion = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers={**bearer(token), "Idempotency-Key": "restart-completion-001"},
            json={"content": "你好，请推荐上海2026年10月旅行"},
        )
        assert completion.status_code == 200, completion.text
        assert completion.json()["message"]["rendered_text"] == "这是持久化的助手回复。"

    second_llm = FakeLLM()
    async with api_client(integration_settings, llm=second_llm) as restarted_client:
        history = await restarted_client.get(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=bearer(token),
        )
        follow_up = await restarted_client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers={**bearer(token), "Idempotency-Key": "restart-completion-002"},
            json={"content": "预算控制在一千元以内"},
        )

    assert history.status_code == 200
    assert [message["role"] for message in history.json()["data"]] == ["user", "assistant"]
    assert follow_up.status_code == 200, follow_up.text
    assert [message.content for message in second_llm.calls[0]] == [
        "You are a travel assistant. Respond in the user's language. "
        "State uncertainty clearly and never invent sources, current weather, "
        "opening hours, or booking availability.",
        "你好，请推荐上海2026年10月旅行",
        "这是持久化的助手回复。",
        "预算控制在一千元以内",
    ]


@pytest.mark.anyio
async def test_failed_completion_is_replayed_as_the_same_safe_error(
    integration_settings: Settings,
) -> None:
    async with api_client(integration_settings, llm=UnavailableLLM()) as client:
        token = await access_token(client)
        created = await client.post("/api/v1/conversations", headers=bearer(token), json={})
        assert created.status_code == 201, created.text
        path = f"/api/v1/conversations/{created.json()['id']}/messages"
        headers = {**bearer(token), "Idempotency-Key": "unavailable-completion-001"}
        payload = {"content": "请安排上海2026年10月旅行"}

        first = await client.post(path, headers=headers, json=payload)
        replay = await client.post(path, headers=headers, json=payload)

    assert first.status_code == 503
    assert first.json()["code"] == "llm_unavailable"
    assert replay.status_code == 503
    assert replay.json()["code"] == "llm_unavailable"
