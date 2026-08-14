"""Durable execution of one authorized conversation turn."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
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
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise APIError(
                409,
                "conversation_busy",
                "A response is already being generated for this conversation.",
            ) from error

        bind_context(run_id=str(run.id), thread_id=str(conversation.thread_id))
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
            assistant = await self._append_message(
                conversation,
                MessageCreate(
                    sequence=conversation.latest_message_sequence + 1,
                    role="assistant",
                    content=[{"type": "text", "text": answer}],
                    rendered_text=answer,
                    agent_run_id=run.id,
                    model_alias="travel-assistant",
                ),
            )
            run.status = "completed"
            run.completed_at = _now()
            self.session.add(run)
            await self.session.commit()
            await self.session.refresh(assistant)
            return ConversationExecutionResult(run=run, message=assistant)
        except Exception as error:
            await self._mark_failed(run, error)
            if isinstance(error, APIError):
                raise
            raise

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

    async def _mark_failed(self, run: AgentRun, error: Exception) -> None:
        """Leave a traceable terminal run record when graph execution raises."""

        await self.session.rollback()
        run.status = "failed"
        run.completed_at = _now()
        if isinstance(error, APIError):
            run.error_code = error.code
        else:
            run.error_code = "agent_execution_failed"
        self.session.add(run)
        await self.session.commit()
