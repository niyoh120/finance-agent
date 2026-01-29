from __future__ import annotations

from agno.agent import Agent
from agno.tools.mcp import MCPTools

from ...config import AppConfig
from ...models import WyckoffSignal


def build_wyckoff_analyst(config: AppConfig) -> Agent:
    model = config.get_model_for_agent("wyckoff")
    mcp_tools = MCPTools(
        url=config.mcp_server.url,
        include_tools=["fetch_stock_history"],
    )

    instructions = (
        "你是交易史上最伟大的人物理查德·D·威科夫。\n"
        "使用 fetch_stock_history 获取K线数据，识别当前所处阶段与关键事件。\n"
        "输出至少3个后续走势情景，给出概率排序，并提供多种交易策略。\n"
        "保持客观严谨，不迎合用户，所有判断要有价量依据。\n"
        "输出 WyckoffSignal。"
    )

    return Agent(
        name="Wyckoff Analyst",
        model=model,
        tools=[mcp_tools],
        instructions=instructions,
        output_schema=WyckoffSignal,
        markdown=True,
        add_datetime_to_context=True,
        reasoning=True,
    )
