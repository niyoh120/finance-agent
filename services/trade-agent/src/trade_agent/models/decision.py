from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .risk import RiskLimits


class TradingDecision(BaseModel):
    ticker: str
    timestamp: datetime
    action: Literal["BUY", "SELL", "HOLD"]
    target_position_size: float = Field(ge=0, le=1)
    confidence: int = Field(ge=0, le=100)
    signals: dict[str, Any] = Field(default_factory=dict)
    risk_limits: RiskLimits
    reasoning: str


class DecisionDraft(BaseModel):
    action: Literal["BUY", "SELL", "HOLD"]
    target_position_size: float = Field(ge=0, le=1)
    confidence: int = Field(ge=0, le=100)
    reasoning: str
