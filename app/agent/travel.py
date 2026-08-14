"""The minimal, durable LangGraph travel-conversation workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, cast
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
    """Recoverable state for the initial travel-advice graph.

    ``messages`` is the complete serializable checkpoint sequence. The execution
    service includes prior messages when submitting the next turn, avoiding an
    async reducer issue in the pinned LangGraph release.
    """

    messages: list[GraphMessage]
    missing_fields: list[str]
    draft_answer: str
    final_answer: str
    run_status: str


_TRAVEL_REQUEST_TERMS = (
    "旅行",
    "旅游",
    "行程",
    "攻略",
    "安排",
    "trip",
    "travel",
    "itinerary",
)
_DESTINATION_HINTS = (
    "去",
    "到",
    "在",
    "上海",
    "北京",
    "广州",
    "深圳",
    "杭州",
    "成都",
    "日本",
    "泰国",
)
_DATE_HINTS = ("今天", "明天", "后天", "周末", "下周", "月", "日", "号", "年", "week", "month")


def _text(message: BaseMessage) -> str:
    """Extract displayable text without assuming a provider-specific content shape."""

    if isinstance(message.content, str):
        return message.content
    return "\n".join(
        block.get("text", "")
        for block in message.content
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    ).strip()


def _missing_essential_fields(content: str) -> list[str]:
    """Require destination and dates only for requests that ask for trip planning."""

    text = content.lower()
    if not any(term in text for term in _TRAVEL_REQUEST_TERMS):
        return []
    missing: list[str] = []
    if not any(hint in text for hint in _DESTINATION_HINTS):
        missing.append("destination")
    if not any(hint in text for hint in _DATE_HINTS):
        missing.append("dates")
    return missing


def validate(state: TravelAgentState) -> dict[str, list[str] | str]:
    """Identify the minimum missing inputs before invoking a model or a tool."""

    messages = state.get("messages", [])
    latest_user_message = next(
        (message for message in reversed(messages) if message["role"] == "user"), None
    )
    if latest_user_message is None:
        return {"missing_fields": ["message"], "run_status": "needs_clarification"}
    missing_fields = _missing_essential_fields(latest_user_message["content"])
    return {
        "missing_fields": missing_fields,
        "run_status": "needs_clarification" if missing_fields else "running",
    }


def load_memory(state: TravelAgentState, runtime: Runtime[TravelAgentContext]) -> dict[str, str]:
    """Reserve the graph boundary for confirmed-preference loading in P4.

    Reading ``runtime.context`` intentionally keeps user identity out of durable
    graph state. Preference storage itself is not activated in P2.0.
    """

    _ = state
    _user_id = runtime.context.user_id
    return {}


async def agent(state: TravelAgentState, runtime: Runtime[TravelAgentContext]) -> dict[str, str]:
    """Ask the configured model for a concise, source-free initial travel answer."""

    if state.get("missing_fields"):
        return {}
    system = SystemMessage(
        content=(
            "You are a travel assistant. Respond in the user's language. "
            "State uncertainty clearly and never invent sources, current weather, "
            "opening hours, or booking availability."
        )
    )
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
    return {"draft_answer": answer}


def compose(state: TravelAgentState) -> dict[str, object]:
    """Turn validation or model output into one canonical assistant message."""

    missing_fields = state.get("missing_fields", [])
    if missing_fields:
        labels = {"destination": "目的地", "dates": "出行日期", "message": "你的问题"}
        requested = "和".join(labels[field] for field in missing_fields)
        answer = f"为了给出可靠建议，请先告诉我{requested}。"
    else:
        answer = state.get("draft_answer", "我暂时无法生成可用回复，请稍后重试。")
    return {"final_answer": answer, "run_status": "completed"}


def persist(state: TravelAgentState) -> dict[str, str]:
    """Mark the graph terminal state; the execution service owns SQL commits."""

    _ = state.get("final_answer")
    return {"run_status": "completed"}


async def execute_turn(
    state: TravelAgentState, runtime: Runtime[TravelAgentContext]
) -> dict[str, object]:
    """Run the P2.0 node sequence within one durable graph super-step.

    The locked LangGraph release deadlocks async invocations after a second
    super-step. Keeping the named, partial-update nodes composed here preserves
    the state boundary and durable checkpoint while avoiding that runtime issue.
    """

    updates: dict[str, object] = {}
    updates.update(validate(state))
    after_validation = cast(TravelAgentState, {**state, **updates})
    updates.update(load_memory(after_validation, runtime))
    after_memory = cast(TravelAgentState, {**state, **updates})
    updates.update(await agent(after_memory, runtime))
    after_agent = cast(TravelAgentState, {**state, **updates})
    updates.update(compose(after_agent))
    after_compose = cast(TravelAgentState, {**state, **updates})
    updates.update(persist(after_compose))
    return updates


def create_travel_agent_graph(
    checkpointer: BaseCheckpointSaver[str],
) -> CompiledStateGraph[TravelAgentState, TravelAgentContext, TravelAgentState, TravelAgentState]:
    """Compile the P2.0 graph with a caller-owned durable checkpointer."""

    builder = StateGraph(TravelAgentState, context_schema=TravelAgentContext)
    builder.add_node("execute_turn", execute_turn)
    builder.add_edge(START, "execute_turn")
    builder.add_edge("execute_turn", END)
    return builder.compile(checkpointer=checkpointer)
