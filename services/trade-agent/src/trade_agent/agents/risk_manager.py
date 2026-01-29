from __future__ import annotations

from agno.agent import Agent

from ..config import AppConfig
from ..models import RiskLimits
from ..tools import calculate_risk_limits


class RiskManager:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._model = config.get_model_for_agent("risk")

    def calculate_hard_limits(self, prices: list[float]) -> RiskLimits:
        params = self._config.risk_parameters
        return calculate_risk_limits(
            prices,
            max_portfolio_volatility=params.max_portfolio_volatility,
            var_confidence=params.var_confidence,
            max_position_limit=params.max_position_limit,
        )

    def adjust_with_llm(
        self, hard_limits: RiskLimits, market_context: str
    ) -> RiskLimits:
        agent = Agent(
            name="Risk Advisor",
            model=self._model,
            instructions=(
                "你是风险管理顾问，只能在硬性约束内提出更保守的建议。\n"
                f"硬性约束: 最大持仓={hard_limits.max_position_size:.2%}, "
                f"单笔最大亏损={hard_limits.max_loss_per_trade:.4f}, "
                f"最大组合波动率={hard_limits.max_portfolio_volatility:.2%}.\n"
                "你可以下调这些值，但不得超过硬性上限。\n"
                f"市场背景: {market_context}"
            ),
            output_schema=RiskLimits,
            markdown=True,
            reasoning=True,
        )

        response = agent.run(
            "根据市场背景调整风险参数", output_schema=RiskLimits, stream=False
        )
        adjusted: RiskLimits = response.content
        return self._enforce_hard_limits(adjusted, hard_limits)

    @staticmethod
    def _enforce_hard_limits(
        adjusted: RiskLimits, hard_limits: RiskLimits
    ) -> RiskLimits:
        return RiskLimits(
            max_position_size=min(
                adjusted.max_position_size, hard_limits.max_position_size
            ),
            max_loss_per_trade=min(
                adjusted.max_loss_per_trade, hard_limits.max_loss_per_trade
            ),
            max_portfolio_volatility=min(
                adjusted.max_portfolio_volatility, hard_limits.max_portfolio_volatility
            ),
            notes=adjusted.notes or hard_limits.notes,
        )
