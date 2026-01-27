from __future__ import annotations

from pydantic import BaseModel, Field


class PortfolioPosition(BaseModel):
    symbol: str
    quantity: float
    average_price: float | None = None
    market_value: float | None = None


class PortfolioState(BaseModel):
    cash: float = Field(ge=0)
    positions: list[PortfolioPosition] = Field(default_factory=list)
