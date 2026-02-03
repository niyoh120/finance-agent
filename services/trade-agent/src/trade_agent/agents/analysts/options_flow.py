from agno.agent import Agent

from ...config import AppConfig
from ...models import OptionsFlowSignal
from ...tools.finance import FinanceTools


def build_options_flow_analyst(config: AppConfig, db=None) -> Agent:
    model = config.get_model_for_agent("options")
    params = config.get_params_for_agent("fundamental")

    return Agent(
        name="Options Flow Analyst",
        model=model,
        tools=[FinanceTools(include_tools=["query_options_flow", "get_flow_summary"])],
        instructions=(
            "你是期权流分析师。使用 query_options_flow 和 get_flow_summary 获取最近14天数据。\n"
            "注意当前时间，不要获取过时的数据。\n"
            "分析 Call/Put 比例、权利金流向、成交量/持仓量比值。\n"
            "关注大额权利金交易与方向性信号。\n"
            "输出 OptionsFlowSignal，包含 call_put_ratio、net_premium、关键大单摘要。\n"
            "尽量使用中文。\n"
        ),
        output_schema=OptionsFlowSignal,
        add_datetime_to_context=True,
        stream=True,
        stream_events=True,
        db=db,
        **params,
    )
