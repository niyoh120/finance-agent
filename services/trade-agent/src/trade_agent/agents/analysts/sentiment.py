from __future__ import annotations

from agno.agent import Agent
from agno.tools.mcp import MCPTools
from agno.tools.yfinance import YFinanceTools

from ...config import AppConfig, build_model
from ...models import SentimentSignal


def build_sentiment_analyst(config: AppConfig) -> Agent:
    model = build_model(config.models["sentiment"])
    mcp_tools = MCPTools(
        url=config.mcp_server.url,
        include_tools=["query_news_articles"],
    )

    return Agent(
        name="Sentiment Analyst",
        model=model,
        tools=[mcp_tools, YFinanceTools(include_tools=["get_company_news"])],
        instructions=(
            "你是新闻情绪分析师。优先使用 query_news_articles 获取内部新闻，"
            "再用 YFinance 新闻补充缺失事件。\n"
            "评估正负面比例、重大事件与市场关注度。\n"
            "输出 SentimentSignal，给出情绪分数(-100~100)与风险提示。"
        ),
        output_schema=SentimentSignal,
        markdown=True,
        add_datetime_to_context=True,
    )
