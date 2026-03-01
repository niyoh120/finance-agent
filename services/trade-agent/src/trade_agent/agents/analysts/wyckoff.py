from agno.agent import Agent

from ...config import AppConfig
from ...tools import FinanceTools, ExaWebSearchTools


def build_wyckoff_analyst(config: AppConfig, db=None) -> Agent:
    model = config.get_model_for_agent("wyckoff")
    params = config.get_params_for_agent("fundamental")

    instructions = (
        "你是交易史上最伟大的人物理查德·D·威科夫。\n"
        "使用 fetch_stock_history 获取K线数据，识别当前所处阶段与关键事件。\n"
        "注意当前时间，不要获取过时的数据。\n"
        "输出至少3个后续走势情景，给出概率排序，并提供多种交易策略。\n"
        "使用中文回答。\n"
    )

    return Agent(
        name="Wyckoff Analyst",
        model=model,
        tools=[
            ExaWebSearchTools(),
            FinanceTools(include_tools=["fetch_stock_history", "search_market"]),
        ],
        instructions=instructions,
        add_datetime_to_context=True,
        markdown=True,
        stream=True,
        stream_events=True,
        db=db,
        **params,
    )
