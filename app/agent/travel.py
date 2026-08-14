"""The minimal, durable LangGraph travel-conversation workflow."""

from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol
from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from typing_extensions import TypedDict


class TravelChatModel(Protocol):
    """The narrow model contract used by the graph and replaceable in tests."""

    async def ainvoke(self, messages: list[BaseMessage]) -> BaseMessage:
        """Return one model response for the supplied canonical message history."""

        ...


@dataclass(frozen=True)
class TravelAgentContext:
    """Request-scoped data available to nodes but excluded from checkpoint state."""

    user_id: UUID
    conversation_id: UUID
    llm: TravelChatModel


class GraphMessage(TypedDict):
    """A checkpoint-serializable chat message owned by the travel graph."""

    role: Literal["user", "assistant"]
    content: str


class TravelAgentState(TypedDict, total=False):
    """Recoverable state for the single-agent travel conversation.

    ``messages`` is the complete serializable checkpoint sequence. The reducer
    appends each newly accepted user message and agent reply, so a caller submits
    only the new turn while LangGraph retains canonical context.
    """

    messages: Annotated[list[GraphMessage], operator.add]
    final_answer: str


TRAVEL_ASSISTANT_SYSTEM_PROMPT = """You are a helpful travel assistant.
Respond in the user's language and use the conversation history to maintain context.
Be clear about uncertainty. Do not invent real-time weather, opening hours, prices,
booking availability, or sources."""


def _text(message: BaseMessage) -> str:
    """Extract displayable text without assuming a provider-specific content shape."""

    if isinstance(message.content, str):
        return message.content
    return "\n".join(
        block.get("text", "")
        for block in message.content
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    ).strip()


async def agent(state: TravelAgentState, runtime: Runtime[TravelAgentContext]) -> dict[str, object]:
    """Generate one reply from the system prompt and the persisted chat history."""

    system = SystemMessage(content=TRAVEL_ASSISTANT_SYSTEM_PROMPT)
    history: list[BaseMessage] = [system]
    for message in state.get("messages", []):
        if message["role"] == "user":
            history.append(HumanMessage(content=message["content"]))
        else:
            history.append(AIMessage(content=message["content"]))
    response = await runtime.context.llm.ainvoke(history)
    answer = _text(response)
    if not answer:
        answer = "我暂时无法生成可用回复，请稍后重试。"
    return {
        "messages": [{"role": "assistant", "content": answer}],
        "final_answer": answer,
    }


def create_travel_agent_graph(
    checkpointer: BaseCheckpointSaver[str],
) -> CompiledStateGraph[TravelAgentState, TravelAgentContext, TravelAgentState, TravelAgentState]:
    """Compile the single-node Agent with a caller-owned durable checkpointer."""

    builder = StateGraph(TravelAgentState, context_schema=TravelAgentContext)
    builder.add_node("agent", agent)
    builder.add_edge(START, "agent")
    builder.add_edge("agent", END)
    return builder.compile(checkpointer=checkpointer)
