from __future__ import annotations

from agno.agent import Agent

from ..config import AppConfig, build_model
from ..models import DecisionDraft


def build_portfolio_manager(config: AppConfig) -> Agent:
    model = build_model(config.models["portfolio"])
    weights = config.analysis.signal_weights

    instructions = (
        "你是投资组合经理，负责汇总所有分析师信号并做出最终决策。\n"
        f"权重参考: {weights}.\n"
        "必须遵守风险管理给出的硬性约束，不能突破最大持仓和最大亏损。\n"
        "输出 DecisionDraft，包含 action/target_position_size/confidence/reasoning。"
    )

    return Agent(
        name="Portfolio Manager",
        model=model,
        instructions=instructions,
        output_schema=DecisionDraft,
        markdown=True,
        add_datetime_to_context=True,
    )
