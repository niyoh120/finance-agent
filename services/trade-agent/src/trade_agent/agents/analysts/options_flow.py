from __future__ import annotations

from agno.agent import Agent
from agno.tools.mcp import MCPTools

from ...config import AppConfig
from ...models import OptionsFlowSignal


def build_options_flow_analyst(config: AppConfig) -> Agent:
    model = config.get_model_for_agent("options")
    mcp_tools = MCPTools(
        url=config.mcp_server.url,
        include_tools=["query_options_flow", "get_flow_summary"],
    )

    return Agent(
        name="Options Flow Analyst",
        model=model,
        tools=[mcp_tools],
        instructions=(
            "你是期权流分析师。使用 query_options_flow 和 get_flow_summary 获取最近14天数据。\n"
            "分析 Call/Put 比例、权利金流向、成交量/持仓量比值。\n"
            "关注大额权利金交易与方向性信号。\n"
            "输出 OptionsFlowSignal，包含 call_put_ratio、net_premium、关键大单摘要。"
        ),
        output_schema=OptionsFlowSignal,
        markdown=True,
        add_datetime_to_context=True,
        reasoning=True,
    )
