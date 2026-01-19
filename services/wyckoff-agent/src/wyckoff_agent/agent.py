from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .compress import extract_pivots
from .data_fetch import MarketDataWindow, fetch_window
from .indicators import compute_moving_averages
from .schemas import (
    CandlesMeta,
    InstrumentType,
    Scenario,
    Strategy,
    Timeframe,
    WyckoffAnalysisResult,
    WyckoffContext,
)
from .wyckoff_candidates import find_volume_spikes, guess_accumulation_zone


@dataclass(frozen=True)
class AgentConfig:
    openai_base_url: str
    openai_api_key: str
    openai_model: str


def load_agent_config() -> AgentConfig:
    base_url = os.getenv("OPENAI_BASE_URL", "").strip()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "").strip() or "gpt-4o"

    if not base_url:
        # Allow default OpenAI if user only provides API key.
        base_url = "https://api.openai.com/v1"

    return AgentConfig(
        openai_base_url=base_url, openai_api_key=api_key, openai_model=model
    )


def build_llm() -> Agent[None, str]:
    cfg = load_agent_config()
    model = OpenAIChatModel(
        cfg.openai_model,
        provider=OpenAIProvider(
            base_url=cfg.openai_base_url, api_key=cfg.openai_api_key
        ),
    )

    system_prompt = (
        "你是交易史上最伟大的人物：理查德·D·威科夫（Richard D. Wyckoff）。\n"
        "你必须客观、严谨，不迎合用户。\n"
        "输出必须为中文，术语使用威科夫体系（SC/AR/ST/Spring/LPS/SOS/UTAD/Phase A-E等）。\n"
        "注意：不要强行凑齐阶段或事件，只输出你能从数据中合理识别到的部分。"
    )

    return Agent(model=model, system_prompt=system_prompt)


async def analyze_symbol_default(symbol: str) -> WyckoffAnalysisResult:
    """Default analysis: 4H timeframe over ~1 year."""

    now = datetime.now(tz=UTC)
    window_4h = MarketDataWindow(
        timeframe=Timeframe.hour_4, start=now - timedelta(days=365), end=now
    )
    candles_4h = await fetch_window(symbol=symbol, window=window_4h)

    ma_4h = (
        compute_moving_averages(timeframe=Timeframe.hour_4, candles=candles_4h)
        if candles_4h
        else None
    )

    zones = []
    zone = guess_accumulation_zone(candles=candles_4h, timeframe=Timeframe.hour_4)
    if zone is not None:
        zones.append(zone)

    events = []
    events.extend(find_volume_spikes(candles=candles_4h, timeframe=Timeframe.hour_4))

    context = WyckoffContext(
        background="待由智能体进一步归因", state="unknown", confidence=0.2
    )

    # For now, scenarios/strategies are placeholder; later tasks will make LLM produce them.
    scenarios = [
        Scenario(
            name="占位：延续震荡",
            probability=0.4,
            triggers=["价格继续在区间内反复"],
            invalidation=["有效放量突破上沿"],
        ),
        Scenario(
            name="占位：向上突破",
            probability=0.35,
            triggers=["放量突破区间上沿"],
            invalidation=["突破后快速回落并跌破区间中枢"],
        ),
        Scenario(
            name="占位：向下破位",
            probability=0.25,
            triggers=["跌破区间下沿且回抽失败"],
            invalidation=["快速收回失地并站回区间"],
        ),
    ]

    strategies = [
        Strategy(
            name="占位：正股做多（突破）",
            instrument_type=InstrumentType.STOCK_LONG,
            entry="放量突破区间上沿后回踩不破再介入",
            stop="回踩跌破上沿且收盘无法收回",
            take_profit="前高附近分批止盈；若放量加速可用 MA50 跟踪",
            risk_notes="突破失败容易形成假突破；注意仓位与滑点。",
        )
    ]

    meta = []
    if candles_4h:
        meta.append(
            CandlesMeta(
                timeframe=Timeframe.hour_4,
                start=window_4h.start,
                end=window_4h.end,
                count=len(candles_4h),
            )
        )

    return WyckoffAnalysisResult(
        symbol=symbol,
        generated_at=now,
        timeframes_used=[Timeframe.hour_4],
        candles_meta=meta,
        wyckoff_context=context,
        phases=[],
        events=events,
        zones=zones,
        moving_averages=[ma_4h] if ma_4h is not None else [],
        scenarios=scenarios,
        strategies=strategies,
        summary="占位：默认 4H/1Y 结构已生成（待 LLM 威科夫归因）",
        details="占位：目前只做了数据拉取、均线与候选事件生成；下一步接入 LLM 生成威科夫阶段/事件理由与策略。",
    )


async def analyze_intraday(symbol: str) -> WyckoffAnalysisResult:
    """Intraday analysis: 1m up to 14 days, plus 60m context."""

    now = datetime.now(tz=UTC)
    w_1m = MarketDataWindow(
        timeframe=Timeframe.minute_1, start=now - timedelta(days=14), end=now
    )
    candles_1m = await fetch_window(symbol=symbol, window=w_1m)

    pivots = extract_pivots(candles=candles_1m)

    # Minimal result: we store pivots count in details.
    context = WyckoffContext(
        background="日内：以结构拐点/量能为主", state="unknown", confidence=0.2
    )

    return WyckoffAnalysisResult(
        symbol=symbol,
        generated_at=now,
        timeframes_used=[Timeframe.minute_1],
        candles_meta=[
            CandlesMeta(
                timeframe=Timeframe.minute_1,
                start=w_1m.start,
                end=w_1m.end,
                count=len(candles_1m),
            )
        ],
        wyckoff_context=context,
        phases=[],
        events=[],
        zones=[],
        moving_averages=[],
        scenarios=[],
        strategies=[],
        summary="占位：日内 1m/14d 数据已拉取并压缩",
        details=f"拐点数={len(pivots.pivots)}；{pivots.notes}",
    )
