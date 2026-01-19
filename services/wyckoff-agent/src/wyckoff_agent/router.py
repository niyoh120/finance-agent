from __future__ import annotations

from dataclasses import dataclass

from .pipeline import run_default
from .schemas import Timeframe, WyckoffAnalysisResult


@dataclass(frozen=True)
class RouteDecision:
    timeframes: list[Timeframe]
    reason: str


def decide_route(*, user_text: str) -> RouteDecision:
    text = user_text.strip().lower()

    intraday_keywords = ["止损", "止盈", "日内", "分钟", "1m", "1分钟", "1 分钟"]
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
    # For now, only default pipeline is implemented; routing will expand later.
    artifacts = await run_default(symbol)
    return (
        artifacts.analysis,
        artifacts.figure_json,
        artifacts.png_path,
        artifacts.analysis_json_path,
        artifacts.figure_json_path,
    )
