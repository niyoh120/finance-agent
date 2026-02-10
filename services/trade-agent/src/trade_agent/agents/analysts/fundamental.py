from agno.agent import Agent
from agno.tools.websearch import WebSearchTools
from agno.tools.yfinance import YFinanceTools

from ...config import AppConfig
from ...tools import FinanceTools


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
            FinanceTools(
                include_tools=[
                    "cn_stock_get_balance_sheet",
                    "cn_stock_get_income_statement",
                    "cn_stock_get_cash_flow",
                    "cn_stock_get_financial_metrics",
                    "cn_stock_get_inner_trade_data",
                    "cn_stock_get_news_data",
                ]
            ),
            WebSearchTools(),
        ],
        instructions=(
            "你是基本面分析师，你擅长使用工具获取数据评估公司内在价值。\n"
            "关注估值(P/E,P/B,PEG)、盈利能力(ROE,利润率)、财务健康(负债率)和成长性, 结合分析师一致预期给出结论。\n"
            "数据源选择策略：\n"
            "- 对于 A 股代码 (通常为 6 位数字，如 '600519', '000001')：\n"
            "  优先使用 `cn_stock_*` 系列工具获取财务三表、财务指标、内部交易数据和个股新闻。\n"
            "  这些工具的 symbol 参数直接使用 6 位代码即可。\n"
            "- 对于美股或其他市场：继续使用 YFinanceTools。\n"
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
