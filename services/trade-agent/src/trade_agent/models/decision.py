from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class TradingDecision(BaseModel):
    ticker: str
    timestamp: datetime
    action: Literal["BUY", "SELL", "HOLD"]
    target_position_size: float = Field(ge=0, le=1)
    confidence: int = Field(ge=0, le=100)
    signals: dict[str, Any] = Field(default_factory=dict)
    risk_limits: dict[str, Any]
    reasoning: str


class DecisionDraft(BaseModel):
    ticker: str = Field(description="Ticker symbol")
    action: Literal["BUY", "SELL", "HOLD"]
    target_position_size: float = Field(ge=0, le=1, description="Target position size")
    confidence: int = Field(ge=0, le=100, description="Confidence level")
    reasoning: str
