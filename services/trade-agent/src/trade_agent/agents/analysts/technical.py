from __future__ import annotations

from agno.agent import Agent
from agno.tools.mcp import MCPTools
from agno.tools.yfinance import YFinanceTools

from ...config import AppConfig, build_model
from ...models import TechnicalSignal
from ...tools import TechnicalIndicatorTools


def build_technical_analyst(config: AppConfig) -> Agent:
    model = build_model(config.models["technical"])
    mcp_tools = MCPTools(
        url=config.mcp_server.url,
        include_tools=["fetch_stock_history"],
    )

    return Agent(
        name="Technical Analyst",
        model=model,
        tools=[
            mcp_tools,
            TechnicalIndicatorTools(),
            YFinanceTools(include_tools=["get_technical_indicators"]),
        ],
        instructions=(
            "你是技术分析师，负责结合内部K线数据与技术指标做出判断。\n"
            f"优先使用 fetch_stock_history 获取 {config.analysis.history_range} 根"
            f"{config.analysis.timeframe} K线，按时间升序计算指标。\n"
            "使用 technical_indicator_tools 计算 RSI/MACD/布林带，"
            "再用 YFinance 的技术指标做交叉验证。\n"
            "如果两个来源结论一致，提升信心；若冲突，说明差异原因。\n"
            "输出 TechnicalSignal，必须包含清晰的趋势判断和理由。"
        ),
        output_schema=TechnicalSignal,
        markdown=True,
        add_datetime_to_context=True,
    )
