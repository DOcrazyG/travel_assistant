"""Durable execution of one authorized conversation turn."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.agent.travel import TravelAgentContext, TravelChatModel
from app.core.errors import APIError
from app.core.logging import bind_context
from app.models.agent_runs import AgentRun
from app.models.conversations import Conversation
from app.models.messages import Message
from app.schemas.messages import MessageCreate
from app.services.crud.messages import MessageCRUD


@dataclass(frozen=True)
class ConversationExecutionResult:
    """The persisted assistant reply and run created for one accepted user turn."""

    run: AgentRun
    message: Message


@dataclass(frozen=True)
class ConversationTurn:
    """Durable records allocated before the Agent starts generating."""

    run: AgentRun
    assistant_message: Message


@dataclass(frozen=True)
class ConversationStreamEvent:
    """One lifecycle event emitted while a single Agent reply is streamed."""

    event: Literal["status", "token", "final"]
    run: AgentRun
    message: Message
    delta: str | None = None
    result: ConversationExecutionResult | None = None


def _now() -> datetime:
    return datetime.now(UTC)


class ConversationExecutionService:
    """Coordinate SQL records and a thread-scoped LangGraph invocation.

    The LangGraph saver commits checkpoints independently. Application-owned
    transcript and run records remain in the request session so their lifecycle,
    authorization, and retention stay under the existing SQLModel boundary.
    """

    def __init__(
        self,
        session: AsyncSession,
        graph: CompiledStateGraph[Any, Any, Any, Any],
        llm: TravelChatModel,
    ) -> None:
        self.session = session
        self.graph = graph
        self.llm = llm

    async def execute(
        self,
        *,
        conversation: Conversation,
        user_id: UUID,
        content: str,
    ) -> ConversationExecutionResult:
        """Store one user message, run the graph, and persist its assistant reply."""

        turn = await self._begin_turn(conversation=conversation, content=content)
        config: RunnableConfig = {"configurable": {"thread_id": str(conversation.thread_id)}}
        context = TravelAgentContext(
            user_id=user_id,
            conversation_id=conversation.id,
            llm=self.llm,
        )
        try:
            state = await self.graph.ainvoke(
                {"messages": [{"role": "user", "content": content}]},
                config,
                context=context,
            )
            answer = str(state["final_answer"])
            return await self._complete_turn(
                run=turn.run,
                assistant=turn.assistant_message,
                answer=answer,
            )
        except Exception as error:
            await self._mark_failed(turn, error)
            if isinstance(error, APIError):
                raise
            raise

    async def stream(
        self,
        *,
        conversation: Conversation,
        user_id: UUID,
        content: str,
    ) -> AsyncIterator[ConversationStreamEvent]:
        """Stream token deltas while durably completing one conversation turn."""

        turn = await self._begin_turn(conversation=conversation, content=content)
        config: RunnableConfig = {"configurable": {"thread_id": str(conversation.thread_id)}}
        context = TravelAgentContext(
            user_id=user_id,
            conversation_id=conversation.id,
            llm=self.llm,
            stream_tokens=True,
        )
        yield ConversationStreamEvent(event="status", run=turn.run, message=turn.assistant_message)
        try:
            async for update in self.graph.astream(
                {"messages": [{"role": "user", "content": content}]},
                config,
                context=context,
                stream_mode="custom",
            ):
                if not isinstance(update, dict) or update.get("event") != "token":
                    continue
                delta = update.get("delta")
                if isinstance(delta, str) and delta:
                    yield ConversationStreamEvent(
                        event="token",
                        run=turn.run,
                        message=turn.assistant_message,
                        delta=delta,
                    )
            state = await self.graph.aget_state(config)
            answer = str(state.values["final_answer"])
            result = await self._complete_turn(
                run=turn.run,
                assistant=turn.assistant_message,
                answer=answer,
            )
            yield ConversationStreamEvent(
                event="final",
                run=turn.run,
                message=result.message,
                result=result,
            )
        except Exception as error:
            await self._mark_failed(turn, error)
            raise

    async def _begin_turn(self, *, conversation: Conversation, content: str) -> ConversationTurn:
        """Persist a running record, user input, and in-progress assistant item."""

        run = AgentRun(
            conversation_id=conversation.id,
            status="running",
            model_alias="travel-assistant",
            started_at=_now(),
        )
        self.session.add(run)
        try:
            await self.session.flush()
            await self._append_message(
                conversation,
                MessageCreate(
                    sequence=conversation.latest_message_sequence + 1,
                    role="user",
                    content=[{"type": "text", "text": content}],
                    rendered_text=content,
                    agent_run_id=run.id,
                ),
            )
            assistant = await self._append_message(
                conversation,
                MessageCreate(
                    sequence=conversation.latest_message_sequence + 1,
                    role="assistant",
                    content=[],
                    content_status="partial",
                    agent_run_id=run.id,
                    model_alias="travel-assistant",
                ),
            )
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise APIError(
                409,
                "conversation_busy",
                "A response is already being generated for this conversation.",
            ) from error
        bind_context(run_id=str(run.id), thread_id=str(conversation.thread_id))
        return ConversationTurn(run=run, assistant_message=assistant)

    async def _complete_turn(
        self,
        *,
        run: AgentRun,
        assistant: Message,
        answer: str,
    ) -> ConversationExecutionResult:
        """Persist one completed assistant reply and close its run."""

        assistant.content = [{"type": "text", "text": answer}]
        assistant.rendered_text = answer
        assistant.content_status = "complete"
        assistant.model_alias = "travel-assistant"
        assistant.updated_at = _now()
        self.session.add(assistant)
        run.status = "completed"
        run.completed_at = _now()
        self.session.add(run)
        await self.session.commit()
        await self.session.refresh(assistant)
        return ConversationExecutionResult(run=run, message=assistant)

    async def _append_message(
        self,
        conversation: Conversation,
        data: MessageCreate,
    ) -> Message:
        """Append an ordered transcript message and advance conversation metadata."""

        message = await MessageCRUD(self.session, conversation.id).create(data)
        conversation.latest_message_sequence = data.sequence
        conversation.last_message_at = _now()
        conversation.updated_at = _now()
        self.session.add(conversation)
        return message

    async def _mark_failed(self, turn: ConversationTurn, error: Exception) -> None:
        """Leave a traceable terminal run record when graph execution raises."""

        await self.session.rollback()
        turn.assistant_message.content_status = "failed"
        turn.assistant_message.updated_at = _now()
        self.session.add(turn.assistant_message)
        run = turn.run
        run.status = "failed"
        run.completed_at = _now()
        if isinstance(error, APIError):
            run.error_code = error.code
        else:
            run.error_code = "agent_execution_failed"
        self.session.add(run)
        await self.session.commit()
