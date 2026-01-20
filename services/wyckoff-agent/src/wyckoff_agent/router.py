"""路由逻辑

该模块根据用户输入决定使用哪种分析流程（默认 vs 日内）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .pipeline import run_default, run_intraday
from .schemas import Timeframe, WyckoffAnalysisResult


@dataclass(frozen=True)
class RouteDecision:
    """路由决策"""

    timeframes: list[Timeframe]
    reason: str


def decide_route(*, user_text: str) -> RouteDecision:
    """根据用户输入决定分析路由

    Args:
        user_text: 用户输入文本

    Returns:
        RouteDecision 包含推荐的 timeframes 和理由
    """
    text = user_text.strip().lower()

    intraday_keywords = [
        "止损",
        "止盈",
        "日内",
        "分钟",
        "1m",
        "1分钟",
        "1 分钟",
        "intraday",
    ]
    if any(k in user_text for k in intraday_keywords):
        return RouteDecision(
            timeframes=[Timeframe.minute_1, Timeframe.hour_1],
            reason="检测到日内风控语义，优先使用1分钟（<=14天）并辅以1小时背景",
        )

    return RouteDecision(
        timeframes=[Timeframe.hour_4], reason="默认使用4小时线覆盖一年趋势"
    )


async def run_for_message(
    *, symbol: str, user_text: str
) -> tuple[WyckoffAnalysisResult, dict, str | None, str | None, str | None]:
    """根据用户消息路由到合适的分析流程

    Args:
        symbol: 股票代码
        user_text: 用户输入文本

    Returns:
        元组包含：(分析结果, figure_json, png_path, analysis_json_path, figure_json_path)
    """
    decision = decide_route(user_text=user_text)

    # 根据路由决策选择流程
    if Timeframe.minute_1 in decision.timeframes:
        artifacts = await run_intraday(symbol)
    else:
        artifacts = await run_default(symbol)

    return (
        artifacts.analysis,
        artifacts.figure_json,
        artifacts.png_path,
        artifacts.analysis_json_path,
        artifacts.figure_json_path,
    )
