"""OpenAI-compatible model construction kept outside graph nodes."""

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from app.agent.travel import TravelChatModel
from app.core.config import Settings
from app.core.errors import APIError


class OpenAICompatibleLLM(TravelChatModel):
    """Create a configured LangChain model only when a graph invocation needs it."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def ainvoke(self, messages: list[BaseMessage]) -> BaseMessage:
        api_key = self.settings.openai_api_key
        model = self.settings.default_llm_model or ""
        if (
            api_key is None
            or api_key.get_secret_value() == "replace-me"
            or not model
            or model == "replace-me"
        ):
            raise APIError(
                503,
                "llm_not_configured",
                "The travel model is not configured yet.",
            )
        client = ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=self.settings.openai_base_url,
            timeout=self.settings.llm_timeout_seconds,
            max_retries=self.settings.llm_max_retries,
        )
        return await client.ainvoke(messages)
