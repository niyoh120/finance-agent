from __future__ import annotations

from agno.agent import Agent
from agno.tools.yfinance import YFinanceTools

from ...config import AppConfig, build_model
from ...models import FundamentalSignal


def build_fundamental_analyst(config: AppConfig) -> Agent:
    model = build_model(config.models["fundamental"])

    return Agent(
        name="Fundamental Analyst",
        model=model,
        tools=[
            YFinanceTools(
                include_tools=[
                    "get_company_info",
                    "get_stock_fundamentals",
                    "get_income_statements",
                    "get_key_financial_ratios",
                    "get_analyst_recommendations",
                ]
            )
        ],
        instructions=(
            "你是基本面分析师，使用 Yahoo Finance 数据评估公司内在价值。\n"
            "关注估值(P/E,P/B,PEG)、盈利能力(ROE,利润率)、财务健康(负债率)和成长性。\n"
            "结合分析师一致预期给出结论。\n"
            "输出 FundamentalSignal，包含估值水平、财务健康结论与关键指标。"
        ),
        output_schema=FundamentalSignal,
        markdown=True,
        add_datetime_to_context=True,
    )
