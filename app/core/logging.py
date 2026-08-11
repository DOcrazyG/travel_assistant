"""Structlog configuration and request-scoped correlation context."""

import logging
import sys
from collections.abc import Mapping
from contextvars import ContextVar, Token
from typing import Any

import structlog

from app.core.config import Settings

_request_context: ContextVar[dict[str, str] | None] = ContextVar("request_context", default=None)


def clear_context() -> Token[dict[str, str] | None]:
    """Start an empty request context and return a token for safe restoration."""

    return _request_context.set({})


def reset_context(token: Token[dict[str, str] | None]) -> None:
    """Restore the context that was active before handling a request."""

    _request_context.reset(token)


def bind_context(**values: str | None) -> None:
    """Add safe correlation values to all structlog events in this request."""

    current = _request_context.get() or {}
    _request_context.set(
        {
            **current,
            **{key: value for key, value in values.items() if value is not None},
        }
    )


def get_context() -> Mapping[str, str]:
    """Return a copy of the active request's correlation values."""

    return dict(_request_context.get() or {})


def add_request_context(
    _: Any,
    __: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Merge correlation fields into each event without overriding explicit fields."""

    return {**get_context(), **event_dict}


def configure_logging(settings: Settings) -> None:
    """Configure console logs locally and JSON logs in deployed environments."""

    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", level=log_level, stream=sys.stdout)

    processors: list[Any] = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        add_request_context,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: Any
    if settings.effective_log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*processors, renderer],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger that emits the active request correlation context."""

    return structlog.get_logger(name)
