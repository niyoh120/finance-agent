from pydantic import BaseModel, Field


class RiskLimits(BaseModel):
    max_position_size: float = Field(ge=0, le=1, description="最大仓位比例")
    max_loss_per_trade: float = Field(ge=0, description="最大单笔损失比例")
    max_portfolio_volatility: float = Field(ge=0, description="最大组合波动率")
    notes: str | None = None
