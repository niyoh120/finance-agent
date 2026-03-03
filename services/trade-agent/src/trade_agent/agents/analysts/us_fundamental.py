from agno.agent import Agent
from agno.tools.yfinance import YFinanceTools

from ...config import AppConfig
from ...tools import ExaWebSearchTools


def build_us_fundamental_analyst(config: AppConfig, db=None) -> Agent:
    """美股基本面分析师

    适用于：
    - 美股：字母代码（如 'AAPL', 'TSLA', 'MSFT'）
    - ETF/ADR等：如 'QQQ', 'BABA'（阿里ADR）
    """
    model = config.get_model_for_agent("fundamental")
    params = config.get_params_for_agent("fundamental")

    instructions = (
        "你是美股基本面分析师，专注于评估美国上市公司的内在价值。\n"
        "\n"
        "分析框架：\n"
        "1. 公司概况：行业地位、商业模式、竞争优势（护城河）\n"
        "2. 盈利能力：ROE、ROA、毛利率、营业利润率、净利润率\n"
        "3. 成长性：营收增长率、EPS增长率、自由现金流增长率\n"
        "4. 财务健康：负债权益比、流动比率、利息覆盖率\n"
        "5. 估值水平：P/E、Forward P/E、P/B、P/S、PEG、EV/EBITDA\n"
        "6. 股东回报：股息率、股息增长、股票回购\n"
        "7. 市场情绪：分析师评级、目标价、机构持仓变动\n"
        "\n"
        "工具使用指南（按优先级）：\n"
        "1) get_company_info(ticker) - 公司基本信息\n"
        "   - 行业、市值、员工数、业务描述\n"
        "\n"
        "2) get_stock_fundamentals(ticker) - 基本面指标汇总\n"
        "   - 关键财务比率、估值指标\n"
        "\n"
        "3) get_income_statements(ticker) - 利润表历史\n"
        "   - 季度/年度营收、利润、EPS趋势\n"
        "\n"
        "4) get_key_financial_ratios(ticker) - 财务比率明细\n"
        "   - 盈利能力、效率、流动性、杠杆、估值比率\n"
        "\n"
        "5) get_analyst_recommendations(ticker) - 分析师评级\n"
        "   - 买入/持有/卖出分布、目标价中位数\n"
        "\n"
        "代码格式：\n"
        "- 直接使用股票代码，如 'AAPL'（苹果）、'TSLA'（特斯拉）、'MSFT'（微软）\n"
        "- 中概股ADR也可用，如 'BABA'（阿里巴巴）、'JD'（京东）、'PDD'（拼多多）\n"
        "- ETF如 'SPY'、'QQQ'、'VOO'\n"
        "\n"
        "分析要点：\n"
        "- 关注季度财报指引（Guidance）的变化\n"
        "- 对比Forward P/E与Trailing P/E判断预期变化\n"
        "- 重视自由现金流（FCF）质量，美股更看重FCF而非净利润\n"
        "- 机构投资者的持仓变化是重要信号\n"
        "\n"
        "输出要求：\n"
        "- 使用中文回答\n"
        "- 给出明确的投资建议（强烈买入/买入/中性/减持/强烈减持）\n"
        "- 列出关键财务指标的具体数值及同比/环比变化\n"
        "- 分析竞争优势和主要风险因素"
    )

    return Agent(
        name="US Fundamental Analyst",
        model=model,
        tools=[
            YFinanceTools(
                enable_company_info=True,
                enable_stock_fundamentals=True,
                enable_income_statements=True,
                enable_key_financial_ratios=True,
                enable_analyst_recommendations=True,
                include_tools=[
                    "get_company_info",
                    "get_stock_fundamentals",
                    "get_income_statements",
                    "get_key_financial_ratios",
                    "get_analyst_recommendations",
                ]
            ),
            ExaWebSearchTools(),
        ],
        instructions=instructions,
        add_datetime_to_context=True,
        markdown=True,
        stream=True,
        stream_events=True,
        db=db,
        **params,
    )
