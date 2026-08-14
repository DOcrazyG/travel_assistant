"""Unit tests for the P2.0 LangGraph travel loop."""

from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.travel import TravelAgentContext, create_travel_agent_graph


class FakeLLM:
    """A deterministic model substitute that records graph inputs."""

    def __init__(self) -> None:
        self.calls: list[list[BaseMessage]] = []

    async def ainvoke(self, messages: list[BaseMessage]) -> BaseMessage:
        self.calls.append(messages)
        return AIMessage(content="上海周末可以先游览外滩，再根据天气调整行程。")


@pytest.mark.anyio
async def test_incomplete_itinerary_request_asks_for_constraints_without_calling_llm() -> None:
    llm = FakeLLM()
    graph = create_travel_agent_graph(InMemorySaver())
    context = TravelAgentContext(user_id=uuid4(), conversation_id=uuid4(), llm=llm)

    state = await graph.ainvoke(
        {"messages": [{"role": "user", "content": "请帮我安排旅行行程"}]},
        {"configurable": {"thread_id": "clarification-thread"}},
        context=context,
    )

    assert state["final_answer"] == "为了给出可靠建议，请先告诉我目的地和出行日期。"
    assert llm.calls == []


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
    checkpoint = await graph.aget_state(config)
    assert checkpoint.values["final_answer"] == state["final_answer"]
