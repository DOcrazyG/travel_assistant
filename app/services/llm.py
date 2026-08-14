"""OpenAI-compatible model construction kept outside graph nodes."""

from collections.abc import AsyncIterator

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.agent.travel import TravelChatModel
from app.core.config import Settings
from app.core.errors import APIError


class OpenAICompatibleLLM(TravelChatModel):
    """Call configured OpenAI-compatible models with an optional fallback."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def registered_models(self) -> tuple[str, ...]:
        """Return the ordered, usable primary and fallback model aliases."""

        primary = self._usable_model_name(self.settings.default_llm_model)
        fallback = self._usable_model_name(self.settings.fallback_llm_model)
        if primary is None:
            return ()
        if fallback is None or fallback == primary:
            return (primary,)
        return (primary, fallback)

    async def ainvoke(self, messages: list[BaseMessage]) -> BaseMessage:
        """Invoke the primary model, then one configured fallback on failure."""

        api_key, models = self._configured_models()

        for index, model in enumerate(models):
            client = ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url=self.settings.openai_base_url,
                timeout=self.settings.llm_timeout_seconds,
                max_retries=self.settings.llm_max_retries,
            )
            try:
                return await client.ainvoke(messages)
            except Exception:
                if index == len(models) - 1:
                    raise

        raise AssertionError("At least one configured model must be invoked")

    async def astream(self, messages: list[BaseMessage]) -> AsyncIterator[BaseMessage]:
        """Yield primary-model chunks, failing over only before output begins."""

        api_key, models = self._configured_models()
        for index, model in enumerate(models):
            emitted_output = False
            client = ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url=self.settings.openai_base_url,
                timeout=self.settings.llm_timeout_seconds,
                max_retries=self.settings.llm_max_retries,
            )
            try:
                async for chunk in client.astream(messages):
                    emitted_output = True
                    yield chunk
                return
            except Exception:
                if emitted_output or index == len(models) - 1:
                    raise

        raise AssertionError("At least one configured model must be invoked")

    def _configured_models(self) -> tuple[SecretStr, tuple[str, ...]]:
        """Validate credentials and return the ordered configured model aliases."""

        api_key = self.settings.openai_api_key
        models = self.registered_models
        if (
            api_key is None
            or api_key.get_secret_value() == "replace-me"
            or not models
        ):
            raise APIError(
                503,
                "llm_not_configured",
                "The travel model is not configured yet.",
            )
        return api_key, models

    @staticmethod
    def _usable_model_name(value: str | None) -> str | None:
        """Normalize optional model settings and ignore placeholder values."""

        if value is None:
            return None
        normalized = value.strip()
        if not normalized or normalized == "replace-me":
            return None
        return normalized
