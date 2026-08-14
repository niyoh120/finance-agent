"""Shared logging configuration.

Goals:
- Always output JSON logs for all Python services.
- Include timestamp, level, logger name, module/filename and line number.
- Resolve log level by priority: FA_{SERVICE}_LOG_LEVEL > FA_LOG_LEVEL.

Implementation notes:
- Uses structlog + stdlib logging ProcessorFormatter so existing
  `logging.getLogger()` calls keep working.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from functools import partial

import structlog

_CONFIGURED = False


def _normalize_service(service: str | None) -> str | None:
    if not service:
        return None
    return service.strip().upper().replace("-", "_")


def _resolve_log_level_name(service: str | None) -> str:
    normalized = _normalize_service(service)

    if normalized:
        value = os.getenv(f"FA_{normalized}_LOG_LEVEL")
        if value and value.strip():
            return value.strip().upper()

    value = os.getenv("FA_LOG_LEVEL")
    if value and value.strip():
        return value.strip().upper()

    return "INFO"


def configure_logging(*, service: str | None = None) -> None:
    """配置全局 logging/structlog。

    Args:
        service: 服务标识（例如: "options-scraper"），用于读取
            `FA_{SERVICE}_LOG_LEVEL` 覆盖 `FA_LOG_LEVEL`。
    """

    global _CONFIGURED
    if _CONFIGURED:
        return

    level_name = _resolve_log_level_name(service)
    level = logging.getLevelName(level_name)
    if not isinstance(level, int):
        level = logging.INFO

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    callsite = structlog.processors.CallsiteParameterAdder(
        {
            structlog.processors.CallsiteParameter.MODULE,
            structlog.processors.CallsiteParameter.FILENAME,
            structlog.processors.CallsiteParameter.LINENO,
        }
    )

    shared_pre_chain = [
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.ExtraAdder(),
        timestamper,
        callsite,
    ]

    # 让 stdlib logging 也走 structlog 渲染，保证全量 JSON 输出。
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    json_serializer = partial(json.dumps, ensure_ascii=False, default=str)
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_pre_chain,
        processors=[
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(serializer=json_serializer),
        ],
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # structlog 本身也配置为兼容 logging.Logger 的 API。
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            timestamper,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            callsite,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    _CONFIGURED = True
