from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SignalDirection(str, Enum):
    bullish = "bullish"
    bearish = "bearish"
    neutral = "neutral"


class TechnicalSignal(BaseModel):
    signal: SignalDirection
    confidence: int = Field(ge=0, le=100)
    rsi: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    bbands_upper: float | None = None
    bbands_middle: float | None = None
    bbands_lower: float | None = None
    trend: str | None = None
    reasoning: str


class OptionsFlowSignal(BaseModel):
    signal: SignalDirection
    confidence: int = Field(ge=0, le=100)
    call_put_ratio: float | None = None
    net_premium: float | None = None
    key_flows: list[str] = Field(default_factory=list)
    reasoning: str


class SentimentSignal(BaseModel):
    signal: SignalDirection
    confidence: int = Field(ge=0, le=100)
    sentiment_score: int = Field(ge=-100, le=100)
    key_headlines: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    reasoning: str


class FundamentalSignal(BaseModel):
    signal: SignalDirection
    confidence: int = Field(ge=0, le=100)
    valuation: str
    financial_health: str
    analyst_consensus: str | None = None
    key_metrics: dict[str, Any] = Field(default_factory=dict)
    reasoning: str


class WyckoffSignal(BaseModel):
    signal: SignalDirection
    confidence: int = Field(ge=0, le=100)
    phase: str | None = None
    key_events: list[str] = Field(default_factory=list)
    scenarios: list[str] = Field(default_factory=list)
    strategies: list[str] = Field(default_factory=list)
    reasoning: str
