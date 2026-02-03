from agno.agent import Agent
from agno.tools.websearch import WebSearchTools
from agno.tools.yfinance import YFinanceTools

from ..config import AppConfig
from ..models import RiskLimits
from ..tools import FinanceTools, calculate_risk_limits


def build_risk_manager(config: AppConfig, db=None) -> Agent:
    model = config.get_model_for_agent("risk")
    params = config.get_params_for_agent("risk")

    def calculate_hard_limits(prices: list[float]) -> RiskLimits:
        params = config.risk_parameters
        return calculate_risk_limits(
            prices,
            max_portfolio_volatility=params.max_portfolio_volatility,
            var_confidence=params.var_confidence,
            max_position_limit=params.max_position_limit,
        )

    instructions = (
        "你是投资风险管理顾问，通过工具获取投资标的基本信息和历史价格，调用计算工具得到硬性约束，并在硬性约束内根据标的特点提出风控建议。 \n"
        "注意当前时间，不要获取过时的数据。\n"
        "输出RiskLimits。\n"
        "尽量使用中文。\n"
    )

    agent = Agent(
        name="Risk Manager",
        model=model,
        tools=[
            YFinanceTools(
                include_tools=[
                    "get_company_info",
                    "get_stock_fundamentals",
                    "get_income_statements",
                    "get_key_financial_ratios",
                ]
            ),
            WebSearchTools(),
            FinanceTools(include_tools=["fetch_stock_history", "search_market"]),
            calculate_hard_limits,
        ],
        instructions=instructions,
        output_schema=RiskLimits,
        add_datetime_to_context=True,
        stream=True,
        stream_events=True,
        db=db,
        **params,
    )

    return agent
