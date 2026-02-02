from agno.agent import Agent
from agno.tools.mcp import MCPTools
from agno.tools.yfinance import YFinanceTools

from ...config import AppConfig
from ...models import TechnicalSignal
from ...tools import TechnicalIndicatorTools


def build_technical_analyst(config: AppConfig) -> Agent:
    model = config.get_model_for_agent("technical")
    params = config.get_params_for_agent("fundamental")

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
            "使用 fetch_stock_history 时，symbol 必须为 TradingView market id：EXCHANGE:SYMBOL。\n"
            "支持的 EXCHANGE 白名单：NASDAQ, NYSE, AMEX, SSE, SZSE, HKEX, BINANCE, COINBASE, KRAKEN, OKX, BYBIT, BITSTAMP, CRYPTOCOM。\n"
            "如果用户只提供裸 ticker（如 AAPL/TSLA/000001），不要猜交易所前缀：需要先向用户追问其交易所/市场。\n"
            f"优先使用 fetch_stock_history 获取 {config.analysis.history_range} 根"
            f"{config.analysis.timeframe} K线，按时间升序计算指标。\n"
            "注意当前时间，不要获取过时的数据。\n"
            "使用 technical_indicator_tools 计算 RSI/MACD/布林带，"
            "再跟用工具获取的技术指标做交叉验证。\n"
            "如果两个来源结论一致，提升信心；若冲突，说明差异原因。\n"
            "输出 TechnicalSignal，必须包含清晰的趋势判断和理由。"
        ),
        output_schema=TechnicalSignal,
        add_datetime_to_context=True,
        **params,
    )
