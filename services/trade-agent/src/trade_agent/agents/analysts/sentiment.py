from agno.agent import Agent
from agno.tools.mcp import MCPTools
from agno.tools.websearch import WebSearchTools
from agno.tools.yfinance import YFinanceTools

from ...config import AppConfig
from ...models import SentimentSignal


def build_sentiment_analyst(config: AppConfig) -> Agent:
    model = config.get_model_for_agent("sentiment")
    params = config.get_params_for_agent("fundamental")

    mcp_tools = MCPTools(
        url=config.mcp_server.url,
        include_tools=["query_news_articles"],
    )

    return Agent(
        name="Sentiment Analyst",
        model=model,
        tools=[
            mcp_tools,
            YFinanceTools(include_tools=["get_company_news"]),
            WebSearchTools(),
        ],
        instructions=(
            "你是新闻情绪分析师。你的任务是使用工具获取股票及市场的相关新闻，评估正负面比例、重大事件与市场关注度。\n"
            "输出 SentimentSignal，给出情绪分数(-100~100)与风险提示。"
        ),
        output_schema=SentimentSignal,
        add_datetime_to_context=True,
        **params,
    )
