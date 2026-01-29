from pydantic import BaseModel, Field


class RiskLimits(BaseModel):
    max_position_size: float = Field(ge=0, le=1)
    max_loss_per_trade: float = Field(ge=0)
    max_portfolio_volatility: float = Field(ge=0)
    notes: str | None = None
