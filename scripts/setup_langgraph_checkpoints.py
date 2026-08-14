"""Provision LangGraph-owned checkpoint tables outside Alembic migrations."""

import asyncio

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import Settings
from app.core.database import create_checkpoint_database_url


async def setup() -> None:
    """Apply dependency-owned, idempotent LangGraph checkpoint migrations once."""

    settings = Settings()
    async with AsyncPostgresSaver.from_conn_string(
        create_checkpoint_database_url(settings)
    ) as checkpointer:
        await checkpointer.setup()


if __name__ == "__main__":
    asyncio.run(setup())
