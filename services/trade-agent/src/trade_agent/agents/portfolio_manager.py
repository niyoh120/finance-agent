from agno.agent import Agent

from ..config import AppConfig


def build_portfolio_manager(config: AppConfig) -> Agent:
    model = config.get_model_for_agent("portfolio")
    params = config.get_params_for_agent("fundamental")
    weights = config.analysis.signal_weights

    instructions = (
        "你是投资组合经理，负责汇总所有分析师信号并做出最终决策。\n"
        f"权重参考: {weights}.\n"
        "必须遵守风险管理给出的硬性约束，不能突破最大持仓和最大亏损。\n"
        "使用中文回答。\n"
    )

    return Agent(
        name="Portfolio Manager",
        model=model,
        instructions=instructions,
        add_datetime_to_context=True,
        markdown=True,
        stream=True,
        stream_events=True,
        **params,
    )
