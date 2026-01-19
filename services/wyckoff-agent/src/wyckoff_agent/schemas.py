from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Timeframe(str, Enum):
    minute_1 = "1"
    minute_5 = "5"
    minute_15 = "15"
    minute_30 = "30"
    hour_1 = "60"
    hour_4 = "240"
    day_1 = "D"
    week_1 = "W"


class Candle(BaseModel):
    time: int = Field(description="Unix 秒")
    timestamp: int = Field(description="Unix 毫秒")
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


class CandlesMeta(BaseModel):
    timeframe: Timeframe
    start: datetime
    end: datetime
    count: int
    has_gaps: bool = False
    notes: str | None = None


class MovingAverageCross(BaseModel):
    timestamp: datetime
    kind: str = Field(description="golden/death/other")
    price: float | None = None
    note: str | None = None


class MovingAverages(BaseModel):
    timeframe: Timeframe
    ma50: list[float | None] = Field(description="与 candles 对齐")
    ma200: list[float | None] = Field(description="与 candles 对齐")
    crosses: list[MovingAverageCross] = Field(default_factory=list)


class WyckoffPhaseName(str, Enum):
    A = "Phase A"
    B = "Phase B"
    C = "Phase C"
    D = "Phase D"
    E = "Phase E"


class WyckoffPhase(BaseModel):
    name: WyckoffPhaseName
    start: datetime
    end: datetime
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(description="中文：该阶段判定依据")


class WyckoffEventType(str, Enum):
    SC = "SC"
    AR = "AR"
    ST = "ST"
    SPRING = "Spring"
    LPS = "LPS"
    SOS = "SOS"
    UTAD = "UTAD"
    JAC = "JAC"
    SIGN_OF_WEAKNESS = "SOW"
    OTHER = "Other"


class WyckoffEvent(BaseModel):
    type: WyckoffEventType
    timestamp: datetime
    price: float
    timeframe: Timeframe
    reason: str = Field(description="中文：术语 + 理由（可换行）")
    extra: dict[str, Any] = Field(default_factory=dict)


class WyckoffZoneKind(str, Enum):
    ACCUMULATION = "accumulation"
    DISTRIBUTION = "distribution"


class WyckoffZone(BaseModel):
    kind: WyckoffZoneKind
    timeframe: Timeframe
    x0: datetime
    x1: datetime
    y_low: float
    y_high: float
    reason: str = Field(description="中文：区间判定依据")


class Scenario(BaseModel):
    name: str
    probability: float = Field(ge=0.0, le=1.0)
    triggers: list[str] = Field(default_factory=list, description="中文：触发条件")
    invalidation: list[str] = Field(default_factory=list, description="中文：失效条件")


class InstrumentType(str, Enum):
    STOCK_LONG = "stock_long"
    STOCK_SHORT = "stock_short"
    OPTIONS_SHORT_TERM = "options_short_term"
    LEAPS_CALL = "leaps_call"
    OTHER = "other"


class Strategy(BaseModel):
    name: str
    instrument_type: InstrumentType
    entry: str = Field(description="中文：入场条件/参考价")
    stop: str = Field(description="中文：止损")
    take_profit: str = Field(description="中文：止盈")
    risk_notes: str = Field(description="中文：风险提示")


class WyckoffContext(BaseModel):
    background: str = Field(description="中文：价格周期背景/主旋律")
    state: str = Field(
        description="accumulation/distribution/markup/markdown/range/unknown"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    note: str | None = None


class WyckoffOverlay(BaseModel):
    """LLM/规则层产出的“叠加层”。不包含原始K线，只包含结构与文字。"""

    wyckoff_context: WyckoffContext
    phases: list[WyckoffPhase] = Field(default_factory=list)
    events: list[WyckoffEvent] = Field(default_factory=list)
    zones: list[WyckoffZone] = Field(default_factory=list)

    scenarios: list[Scenario] = Field(default_factory=list)
    strategies: list[Strategy] = Field(default_factory=list)

    summary: str = Field(description="中文：总览结论（短）")
    details: str = Field(description="中文：分析过程结论（可多段）")


class WyckoffAnalysisResult(BaseModel):
    symbol: str
    generated_at: datetime
    timeframes_used: list[Timeframe]

    candles_meta: list[CandlesMeta]

    wyckoff_context: WyckoffContext
    phases: list[WyckoffPhase] = Field(default_factory=list)
    events: list[WyckoffEvent] = Field(default_factory=list)
    zones: list[WyckoffZone] = Field(default_factory=list)

    moving_averages: list[MovingAverages] = Field(default_factory=list)

    scenarios: list[Scenario] = Field(default_factory=list)
    strategies: list[Strategy] = Field(default_factory=list)

    summary: str = Field(description="中文：总览结论（短）")
    details: str = Field(description="中文：分析过程结论（可多段）")
