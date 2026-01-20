"""从 Agent 消息历史中提取数据的工具函数

该模块提供从 PydanticAI Agent 的消息历史中提取数据的工具函数，
主要用于从 LLM 调用 MCP tools 的返回结果中提取 K 线数据等信息。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic_ai.messages import ModelMessage, ToolReturnPart

from .schemas import Candle, Timeframe

if TYPE_CHECKING:
    from collections.abc import Sequence


def extract_candles_from_messages(messages: Sequence[ModelMessage]) -> list[Candle]:
    """从消息历史中提取 LLM 通过 fetch_stock_history 获得的 K 线数据

    该函数遍历消息历史，查找 fetch_stock_history 工具的返回结果，
    并从中解析 K 线数据。

    Args:
        messages: Agent run 的消息历史

    Returns:
        K 线数据列表，如果未找到则返回空列表
    """
    # 从最近的消息往回找，找到第一个 fetch_stock_history 的返回结果
    for msg in reversed(messages):
        for part in msg.parts:
            if (
                isinstance(part, ToolReturnPart)
                and part.tool_name == "fetch_stock_history"
            ):
                candles = _parse_candles_from_tool_return(part.content)
                if candles:
                    return candles

    return []


def extract_timeframe_from_messages(
    messages: Sequence[ModelMessage],
) -> Timeframe | None:
    """从消息历史中提取 LLM 使用的 timeframe

    Args:
        messages: Agent run 的消息历史

    Returns:
        Timeframe 枚举值，如果未找到则返回 None
    """
    for msg in reversed(messages):
        for part in msg.parts:
            if (
                isinstance(part, ToolReturnPart)
                and part.tool_name == "fetch_stock_history"
            ):
                tf = _parse_timeframe_from_tool_return(part.content)
                if tf is not None:
                    return tf

    return None


def _parse_candles_from_tool_return(content: str) -> list[Candle]:
    """从工具返回内容中解析 K 线数据

    Args:
        content: 工具返回的 JSON 字符串

    Returns:
        解析后的 Candle 列表
    """
    try:
        data = json.loads(content)

        # 提取 candles 字段
        candles_raw = data.get("candles", [])
        if not isinstance(candles_raw, list):
            return []

        # 转换为 Candle 对象
        candles = []
        for c in candles_raw:
            try:
                candles.append(Candle.model_validate(c))
            except Exception:
                # 跳过无法解析的 candle
                continue

        return candles

    except (json.JSONDecodeError, ValueError, TypeError):
        return []


def _parse_timeframe_from_tool_return(content: str) -> Timeframe | None:
    """从工具返回内容中解析 timeframe

    Args:
        content: 工具返回的 JSON 字符串

    Returns:
        Timeframe 枚举值，如果解析失败返回 None
    """
    try:
        data = json.loads(content)
        tf_str = data.get("timeframe")

        if tf_str:
            return _map_timeframe(tf_str)

    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    return None


def _map_timeframe(tf_str: str) -> Timeframe | None:
    """将 MCP server 的 timeframe 字符串映射到 Timeframe 枚举

    Args:
        tf_str: timeframe 字符串（如 "240", "D" 等）

    Returns:
        对应的 Timeframe 枚举值，如果无法映射返回 None
    """
    mapping = {
        "1": Timeframe.minute_1,
        "5": Timeframe.minute_5,
        "15": Timeframe.minute_15,
        "30": Timeframe.minute_30,
        "60": Timeframe.hour_1,
        "240": Timeframe.hour_4,
        "D": Timeframe.day_1,
        "W": Timeframe.week_1,
    }
    return mapping.get(tf_str)
