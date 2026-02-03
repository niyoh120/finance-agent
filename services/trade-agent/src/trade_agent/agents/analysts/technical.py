from agno.agent import Agent

from ...config import AppConfig
from ...models import TechnicalSignal
from ...tools import FinanceTools, TechnicalIndicatorTools


def build_technical_analyst(config: AppConfig, db=None) -> Agent:
    model = config.get_model_for_agent("technical")
    params = config.get_params_for_agent("fundamental")

    return Agent(
        name="Technical Analyst",
        model=model,
        tools=[
            FinanceTools(include_tools=["fetch_stock_history", "search_market"]),
            TechnicalIndicatorTools(),
        ],
        instructions=(
            "你是技术分析师，负责结合内部K线数据与技术指标做出判断。\n"
            "优先使用 fetch_stock_history 获取 K线数据。 \n"
            "注意当前时间，不要获取过时的数据。\n"
            "使用 technical_indicator_tools 计算 RSI/MACD/布林带，"
            "再跟用工具获取的技术指标做交叉验证。\n"
            "如果两个来源结论一致，提升信心；若冲突，说明差异原因。\n"
            "输出 TechnicalSignal，必须包含清晰的趋势判断和理由。\n"
            "尽量使用中文。\n"
        ),
        output_schema=TechnicalSignal,
        add_datetime_to_context=True,
        stream=True,
        stream_events=True,
        db=db,
        **params,
    )
