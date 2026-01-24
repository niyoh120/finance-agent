"""mcp_server.schemas

MCP server tool schemas.

- Output schemas are Pydantic models to provide MCP output_schema / structuredContent.
- Input schemas are defined directly on tool function parameters (Annotated + Field)
  to avoid wrapping everything under a single "query" parameter.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class McpBaseModel(BaseModel):
    """Base model for MCP schemas.

    - Forbid extra keys: catch hallucinated fields early.
    - Keep defaults: helps schema generation.
    """

    model_config = ConfigDict(extra="forbid")


# =============================
# Output (Result) Models
# =============================


# =============================
# Shared input types (for tool params)
# =============================


OptionsSide = Literal["Bid", "Ask"]
OptionType = Literal["P", "C"]

# NOTE: TradingView timeframe values accepted by @mathieuc/tradingview are strings.
# The list here is intentionally conservative and covers common use cases.
Timeframe = Literal[
    "1",
    "3",
    "5",
    "15",
    "30",
    "45",
    "60",
    "120",
    "180",
    "240",
    "D",
    "W",
    "M",
]


class NewsArticleItem(McpBaseModel):
    """单条新闻文章."""

    external_id: str = Field(description="外部唯一标识")
    type: str = Field(description="新闻类型")
    title: str = Field(description="新闻标题")
    url: str = Field(description="新闻链接")
    author: str | None = Field(description="作者")
    symbols: list[str] = Field(description="相关股票代码列表")
    tags: list[str] = Field(description="标签列表")
    importance: int = Field(description="重要性评分")
    published_at: str = Field(description="发布时间 (ISO 8601 格式)")


class NewsArticlesResult(McpBaseModel):
    """新闻文章查询结果."""

    since: str = Field(description="查询起始时间 (ISO 8601)")
    limit: int = Field(description="每页数量限制")
    offset: int = Field(description="偏移量")
    count: int = Field(description="实际返回数量")
    articles: list[NewsArticleItem] = Field(description="新闻文章列表")


class Candle(McpBaseModel):
    """K 线蜡烛图数据点."""

    time: int = Field(description="时间戳 (Unix timestamp, 秒)")
    timestamp: int = Field(description="时间戳 (Unix timestamp, 毫秒)")
    open: float = Field(description="开盘价")
    high: float = Field(description="最高价")
    low: float = Field(description="最低价")
    close: float = Field(description="收盘价")
    volume: float | None = Field(description="成交量")


class StockHistoryResult(McpBaseModel):
    """股票历史数据查询结果."""

    symbol: str = Field(description="股票代码")
    timeframe: str = Field(description="时间周期")
    range: int = Field(description="请求的数据点数量")
    to: int | None = Field(description="结束时间戳 (Unix timestamp, 秒)", default=None)
    candles: list[Candle] = Field(description="K 线数据列表")


class OptionsFlowItem(McpBaseModel):
    """单条期权大单记录."""

    timestamp: str = Field(description="交易时间 (ISO 8601)")
    symbol: str = Field(description="股票代码")
    strike: float = Field(description="行权价")
    option_type: str = Field(description="期权类型 ('P' 看跌 / 'C' 看涨)")
    expiry: str = Field(description="到期日 (ISO 8601, 日期格式)")
    dte: int = Field(description="距离到期天数 (DTE)")
    side: str = Field(description="交易方向 ('Bid' / 'Ask')")
    interval_volume: int = Field(description="时段内成交量")
    open_interest: int = Field(description="未平仓量 (OI)")
    vol_oi: float = Field(description="成交量/未平仓量比率 (Vol/OI)")
    otm_percent: float = Field(description="价外程度百分比 (OTM %)")
    bid_percent: int = Field(description="买方占比 (%)")
    ask_percent: int = Field(description="卖方占比 (%)")
    premium: float = Field(description="权利金总额 (美元)")
    avg_fill: float = Field(description="平均成交价格")
    multileg_percent: float = Field(description="多腿策略占比 (%)")


class SideStats(McpBaseModel):
    """按交易方向的统计数据."""

    count: int = Field(description="交易数量")
    premium: float = Field(description="总权利金 (美元)")


class TypeStats(McpBaseModel):
    """按期权类型的统计数据."""

    count: int = Field(description="交易数量")
    premium: float = Field(description="总权利金 (美元)")


class TopSymbol(McpBaseModel):
    """Top 活跃标的."""

    symbol: str = Field(description="股票代码")
    count: int = Field(description="交易数量")
    premium: float = Field(description="总权利金 (美元)")


class FlowSummaryResult(McpBaseModel):
    """期权流向汇总统计结果."""

    period_days: int = Field(description="统计周期 (天)")
    total_trades: int = Field(description="总交易数")
    total_premium: float = Field(description="总权利金 (美元)")
    by_side: dict[str, SideStats] = Field(description="按交易方向统计")
    by_type: dict[str, TypeStats] = Field(description="按期权类型统计")
    top_symbols: list[TopSymbol] = Field(description="Top 10 活跃标的")
