"""Wyckoff agent logging helpers."""

from __future__ import annotations

import json
import logging
from typing import Iterable

from pydantic_ai.messages import ModelMessage

from shared.logging import configure_logging as _configure_shared_logging


def configure_logging() -> None:
    """Configure default logging format and level."""
    _configure_shared_logging(service="wyckoff")


def log_agent_messages(
    logger: logging.Logger,
    messages: Iterable[ModelMessage],
    *,
    max_payload: int = 2000,
) -> None:
    """Log agent messages (tool calls and returns)."""
    if not logger.isEnabledFor(logging.DEBUG):
        return

    for idx, msg in enumerate(messages, start=1):
        role = getattr(msg, "role", None)
        logger.debug(
            "agent_message[%s]: type=%s role=%s", idx, type(msg).__name__, role
        )
        parts = getattr(msg, "parts", [])
        for part_idx, part in enumerate(parts, start=1):
            tool_name = getattr(part, "tool_name", None)
            args = getattr(part, "args", None)
            content = getattr(part, "content", None)
            logger.debug(
                "agent_message[%s].part[%s]: type=%s tool=%s",
                idx,
                part_idx,
                type(part).__name__,
                tool_name,
            )
            if args is not None:
                args_str = _safe_json(args)
                logger.debug(
                    "agent_message[%s].part[%s].args=%s", idx, part_idx, args_str
                )
            if isinstance(content, str):
                logger.debug(
                    "agent_message[%s].part[%s].content=%s",
                    idx,
                    part_idx,
                    _truncate_text(content, max_payload),
                )


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "...<truncated>"


def _safe_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)
