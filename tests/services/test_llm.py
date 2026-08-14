"""Tests for the OpenAI-compatible model registration and fallback boundary."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import SecretStr

from app.core.config import Settings
from app.core.errors import APIError
from app.services.llm import OpenAICompatibleLLM


class FakeClient:
    """A scripted ChatOpenAI substitute that records each invocation."""

    def __init__(self, result: AIMessage | Exception) -> None:
        self.result = result
        self.calls: list[list[HumanMessage]] = []

    async def ainvoke(self, messages: list[HumanMessage]) -> AIMessage:
        self.calls.append(messages)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def settings(**updates: object) -> Settings:
    """Build an isolated configured service without reading production secrets."""

    base = Settings(
        openai_api_key=SecretStr("test-api-key"),
        openai_base_url="https://models.example.test/v1",
        default_llm_model="primary-model",
    )
    return base.model_copy(update=updates)


@pytest.mark.anyio
async def test_primary_model_response_does_not_call_the_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = FakeClient(AIMessage(content="primary reply"))
    constructed: list[dict[str, object]] = []

    def fake_chat_openai(**kwargs: object) -> FakeClient:
        constructed.append(kwargs)
        return primary

    monkeypatch.setattr("app.services.llm.ChatOpenAI", fake_chat_openai)
    service = OpenAICompatibleLLM(settings(fallback_llm_model="fallback-model"))

    response = await service.ainvoke([HumanMessage(content="hello")])

    assert response.content == "primary reply"
    assert service.registered_models == ("primary-model", "fallback-model")
    assert [item["model"] for item in constructed] == ["primary-model"]


@pytest.mark.anyio
async def test_fallback_model_is_used_after_primary_call_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients = {
        "primary-model": FakeClient(RuntimeError("primary unavailable")),
        "fallback-model": FakeClient(AIMessage(content="fallback reply")),
    }
    constructed: list[dict[str, object]] = []

    def fake_chat_openai(**kwargs: object) -> FakeClient:
        constructed.append(kwargs)
        return clients[str(kwargs["model"])]

    monkeypatch.setattr("app.services.llm.ChatOpenAI", fake_chat_openai)
    service = OpenAICompatibleLLM(settings(fallback_llm_model="fallback-model"))

    response = await service.ainvoke([HumanMessage(content="hello")])

    assert response.content == "fallback reply"
    assert [item["model"] for item in constructed] == ["primary-model", "fallback-model"]
    assert all(item["base_url"] == "https://models.example.test/v1" for item in constructed)


@pytest.mark.anyio
async def test_service_rejects_missing_primary_model() -> None:
    service = OpenAICompatibleLLM(settings(default_llm_model="replace-me"))

    with pytest.raises(APIError, match="not configured"):
        await service.ainvoke([HumanMessage(content="hello")])
