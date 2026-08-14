"""Unit tests for the durable, single-node travel Agent."""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.travel import (
    TRAVEL_ASSISTANT_SYSTEM_PROMPT,
    TravelAgentContext,
    create_travel_agent_graph,
)


class FakeLLM:
    """A deterministic model substitute that records graph inputs."""

    def __init__(self) -> None:
        self.calls: list[list[BaseMessage]] = []

    async def ainvoke(self, messages: list[BaseMessage]) -> BaseMessage:
        self.calls.append(messages)
        return AIMessage(content="上海周末可以先游览外滩，再根据天气调整行程。")

    async def astream(self, messages: list[BaseMessage]) -> AsyncIterator[BaseMessage]:
        self.calls.append(messages)
        yield AIMessageChunk(content="上海周末可以先游览")
        yield AIMessageChunk(content="外滩，再根据天气调整行程。")


@pytest.mark.anyio
async def test_agent_answers_every_message_without_pre_validation() -> None:
    llm = FakeLLM()
    graph = create_travel_agent_graph(InMemorySaver())
    context = TravelAgentContext(user_id=uuid4(), conversation_id=uuid4(), llm=llm)

    state = await graph.ainvoke(
        {"messages": [{"role": "user", "content": "请帮我安排旅行行程"}]},
        {"configurable": {"thread_id": "clarification-thread"}},
        context=context,
    )

    assert state["final_answer"].startswith("上海周末")
    assert [message.content for message in llm.calls[0]] == [
        TRAVEL_ASSISTANT_SYSTEM_PROMPT,
        "请帮我安排旅行行程",
    ]


@pytest.mark.anyio
async def test_complete_request_uses_llm_and_persists_the_latest_turn_in_one_thread() -> None:
    llm = FakeLLM()
    graph = create_travel_agent_graph(InMemorySaver())
    context = TravelAgentContext(user_id=uuid4(), conversation_id=uuid4(), llm=llm)
    config: RunnableConfig = {"configurable": {"thread_id": "durable-thread"}}

    await graph.ainvoke(
        {"messages": [{"role": "user", "content": "请安排上海周末行程"}]},
        config,
        context=context,
    )
    state = await graph.ainvoke(
        {"messages": [{"role": "user", "content": "预算控制在一千元以内"}]},
        config,
        context=context,
    )

    assert state["final_answer"].startswith("上海周末")
    assert len(llm.calls) == 2
    assert [message.content for message in llm.calls[1]] == [
        TRAVEL_ASSISTANT_SYSTEM_PROMPT,
        "请安排上海周末行程",
        "上海周末可以先游览外滩，再根据天气调整行程。",
        "预算控制在一千元以内",
    ]
    checkpoint = await graph.aget_state(config)
    assert checkpoint.values["final_answer"] == state["final_answer"]
    assert checkpoint.values["messages"][-1] == {
        "role": "assistant",
        "content": state["final_answer"],
    }


@pytest.mark.anyio
async def test_agent_streams_token_deltas_and_persists_the_complete_reply() -> None:
    llm = FakeLLM()
    graph = create_travel_agent_graph(InMemorySaver())
    context = TravelAgentContext(
        user_id=uuid4(),
        conversation_id=uuid4(),
        llm=llm,
        stream_tokens=True,
    )
    config: RunnableConfig = {"configurable": {"thread_id": "stream-thread"}}

    events = [
        event
        async for event in graph.astream(
            {"messages": [{"role": "user", "content": "请推荐上海旅行"}]},
            config,
            context=context,
            stream_mode="custom",
        )
    ]

    assert events == [
        {"event": "token", "delta": "上海周末可以先游览"},
        {"event": "token", "delta": "外滩，再根据天气调整行程。"},
    ]
    checkpoint = await graph.aget_state(config)
    assert checkpoint.values["final_answer"] == "上海周末可以先游览外滩，再根据天气调整行程。"
