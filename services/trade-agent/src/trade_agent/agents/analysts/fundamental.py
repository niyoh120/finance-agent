from agno.agent import Agent
from agno.tools.websearch import WebSearchTools
from agno.tools.yfinance import YFinanceTools

from ...config import AppConfig


def build_fundamental_analyst(config: AppConfig, db=None) -> Agent:
    model = config.get_model_for_agent("fundamental")
    params = config.get_params_for_agent("fundamental")

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
            ),
            WebSearchTools(),
        ],
        instructions=(
            "你是基本面分析师，你擅长使用工具获取数据评估公司内在价值。\n"
            "关注估值(P/E,P/B,PEG)、盈利能力(ROE,利润率)、财务健康(负债率)和成长性, 结合分析师一致预期给出结论。\n"
            "注意当前时间，不要获取过时的数据。\n"
            "使用中文回答。\n"
        ),
        add_datetime_to_context=True,
        markdown=True,
        stream=True,
        stream_events=True,
        db=db,
        **params,
    )
