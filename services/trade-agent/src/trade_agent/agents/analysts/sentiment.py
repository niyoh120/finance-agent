from agno.agent import Agent
from agno.tools.websearch import WebSearchTools
from agno.tools.yfinance import YFinanceTools

from ...config import AppConfig
from ...models import SentimentSignal
from ...tools import FinanceTools


def build_sentiment_analyst(config: AppConfig, db=None) -> Agent:
    model = config.get_model_for_agent("sentiment")
    params = config.get_params_for_agent("fundamental")

    return Agent(
        name="Sentiment Analyst",
        model=model,
        tools=[
            FinanceTools(include_tools=["query_news_articles"]),
            YFinanceTools(include_tools=["get_company_news"]),
            WebSearchTools(),
        ],
        instructions=(
            "你是新闻情绪分析师。你的任务是使用工具获取股票及市场的相关新闻，评估正负面比例、重大事件与市场关注度。\n"
            "输出 SentimentSignal，给出情绪分数(-100~100)与风险提示。\n"
            "注意当前时间，不要获取过时的数据。\n"
            "尽量使用中文。\n"
        ),
        output_schema=SentimentSignal,
        add_datetime_to_context=True,
        stream=True,
        stream_events=True,
        db=db,
        **params,
    )
