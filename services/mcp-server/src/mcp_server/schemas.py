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
NewsType = Literal["macro_news", "kol_tweet", "stock_news"]

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
    source: str | None = Field(description="数据来源 (futunn, bubbleseek 等)")
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
    open: float = Field(description="开盘价")
    high: float = Field(description="最高价")
    low: float = Field(description="最低价")
    close: float = Field(description="收盘价")
    volume: float | None = Field(description="成交量")


class StockHistoryResult(McpBaseModel):
    """股票历史数据查询结果."""

    symbol: str = Field(description="TradingView market id，格式为 EXCHANGE:SYMBOL")
    timeframe: str = Field(description="时间周期")
    range: int = Field(description="请求的数据点数量")
    to: int | None = Field(description="结束时间戳 (Unix timestamp, 秒)", default=None)
    candles: list[Candle] = Field(description="K 线数据列表")


class TradingViewMarketItem(McpBaseModel):
    """TradingView 市场搜索结果条目."""

    id: str = Field(description="TradingView market id，例如 NASDAQ:AAPL")
    exchange: str | None = Field(description="交易所/市场代码", default=None)
    full_exchange: str | None = Field(description="交易所全称", default=None)
    symbol: str | None = Field(description="代码/合约（不含交易所前缀）", default=None)
    description: str | None = Field(description="标的描述", default=None)
    type: str | None = Field(description="标的类型，如 stock/crypto/index", default=None)


class TradingViewMarketSearchResult(McpBaseModel):
    """TradingView 市场搜索结果."""

    query: str = Field(description="搜索关键词")
    type: str | None = Field(description="类型过滤（stock/crypto/...），留空表示不过滤", default=None)
    limit: int = Field(description="返回数量上限")
    offset: int = Field(description="分页偏移")
    count: int = Field(description="实际返回数量")
    results: list[TradingViewMarketItem] = Field(description="候选市场列表")


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


# =============================
# Macro data output models
# =============================


class MacroReportItem(McpBaseModel):
    """宏观报告快照。

    报告来自 The Dial (indexbha.com)，包含当期总指数评分及对比变化，
    用于快速判断宏观金融环境的风险与流动性状态。
    """

    report_date: str = Field(description="报告日期 (YYYY-MM-DD)")
    current_snapshot_date: str | None = Field(description="当前快照日期 (YYYY-MM-DD)")
    compare_date: str | None = Field(description="对比日期 (YYYY-MM-DD)")
    generated_at: str | None = Field(description="报告生成时间 (ISO 8601)")
    current_score: float | None = Field(description="总指数当前评分")
    compare_score: float | None = Field(description="对比日评分")
    change: float | None = Field(description="评分变化值")
    change_pct: float | None = Field(description="评分变化百分比")


class MacroReportsResult(McpBaseModel):
    """宏观报告查询结果。

    返回指定日期范围内的报告快照列表，适合用于回顾总指数趋势或
    作为分析其他宏观子模块的入口。
    """

    start_date: str = Field(description="查询起始日期 (YYYY-MM-DD)")
    end_date: str = Field(description="查询结束日期 (YYYY-MM-DD)")
    limit: int = Field(description="返回数量限制")
    offset: int = Field(description="结果偏移量")
    count: int = Field(description="实际返回数量")
    reports: list[MacroReportItem] = Field(description="宏观报告列表")


class MacroModuleSnapshotItem(McpBaseModel):
    """宏观模块快照。

    The Dial 将宏观指标按模块拆分（如流动性、利率、风险偏好等），
    每条记录代表某一模块在特定报告日的评分与变化。
    """

    report_date: str = Field(description="报告日期 (YYYY-MM-DD)")
    module_id: str = Field(description="模块标识 (英文)")
    name: str | None = Field(description="模块名称 (英文)")
    name_cn: str | None = Field(description="模块名称 (中文)")
    current_score: float | None = Field(description="当前评分")
    compare_score: float | None = Field(description="对比日评分")
    change: float | None = Field(description="评分变化值")
    change_pct: float | None = Field(description="评分变化百分比")


class MacroModuleSnapshotsResult(McpBaseModel):
    """宏观模块快照查询结果。

    用于查看模块级别评分的横截面变化（同一天多个模块）或时间序列变化。
    """

    start_date: str = Field(description="查询起始日期 (YYYY-MM-DD)")
    end_date: str = Field(description="查询结束日期 (YYYY-MM-DD)")
    limit: int = Field(description="返回数量限制")
    offset: int = Field(description="结果偏移量")
    count: int = Field(description="实际返回数量")
    modules: list[MacroModuleSnapshotItem] = Field(description="模块快照列表")


class MacroFactorSnapshotItem(McpBaseModel):
    """宏观因子快照。

    因子是模块下的具体指标（如 SOFR、VIX、美元指数等）。
    该快照提供当前值、分位、对比变化等，用于分析驱动模块变化的具体来源。
    """

    report_date: str = Field(description="报告日期 (YYYY-MM-DD)")
    module_id: str = Field(description="模块标识 (英文)")
    module_name: str | None = Field(description="模块名称 (英文)")
    module_name_cn: str | None = Field(description="模块名称 (中文)")
    factor_id: str = Field(description="因子标识 (英文)")
    name: str | None = Field(description="因子名称 (英文)")
    name_cn: str | None = Field(description="因子名称 (中文)")
    display_only: bool | None = Field(description="是否仅展示 (不参与评分)")
    current_value: float | None = Field(description="当前值")
    current_value_formatted: str | None = Field(description="当前值格式化展示")
    current_percentile: float | None = Field(description="当前分位")
    compare_value: float | None = Field(description="对比日数值")
    compare_value_formatted: str | None = Field(description="对比日数值格式化展示")
    compare_percentile: float | None = Field(description="对比分位")
    value_change: float | None = Field(description="数值变化")
    value_change_pct: float | None = Field(description="数值变化百分比")
    percentile_change: float | None = Field(description="分位变化")
    percentile_change_pct: float | None = Field(description="分位变化百分比")
    color: str | None = Field(description="颜色标记 (风险级别提示)")


class MacroFactorSnapshotsResult(McpBaseModel):
    """宏观因子快照查询结果。

    适合用于深入分析某一模块或因子的细节变化，以及识别主导变化的指标。
    """

    start_date: str = Field(description="查询起始日期 (YYYY-MM-DD)")
    end_date: str = Field(description="查询结束日期 (YYYY-MM-DD)")
    limit: int = Field(description="返回数量限制")
    offset: int = Field(description="结果偏移量")
    count: int = Field(description="实际返回数量")
    factors: list[MacroFactorSnapshotItem] = Field(description="因子快照列表")


class MacroModuleHistoryItem(McpBaseModel):
    """宏观模块历史序列。

    按日期记录模块评分的时间序列数据，可用于趋势分析、回测或可视化。
    """

    date: str = Field(description="日期 (YYYY-MM-DD)")
    module_id: str = Field(description="模块标识 (英文)")
    module_name: str | None = Field(description="模块名称 (英文)")
    module_name_cn: str | None = Field(description="模块名称 (中文)")
    value: float | None = Field(description="模块评分")
    percentile: float | None = Field(description="模块评分分位")


class MacroModuleHistoryResult(McpBaseModel):
    """宏观模块历史查询结果。

    返回指定模块在日期范围内的评分序列，按时间升序排列。
    """

    module_id: str = Field(description="模块标识 (英文)")
    start_date: str = Field(description="查询起始日期 (YYYY-MM-DD)")
    end_date: str = Field(description="查询结束日期 (YYYY-MM-DD)")
    limit: int = Field(description="返回数量限制")
    offset: int = Field(description="结果偏移量")
    count: int = Field(description="实际返回数量")
    history: list[MacroModuleHistoryItem] = Field(description="模块历史序列")


class MacroTotalIndexHistoryItem(McpBaseModel):
    """宏观总指数历史序列。

    反映整体宏观环境变化的时间序列数据，适合作为宏观风险/流动性的总览指标。
    """

    date: str = Field(description="日期 (YYYY-MM-DD)")
    value: float | None = Field(description="总指数评分")
    percentile: float | None = Field(description="总指数分位")


class MacroTotalIndexHistoryResult(McpBaseModel):
    """宏观总指数历史查询结果。

    返回指定日期范围内的总指数历史序列，按时间升序排列。
    """

    start_date: str = Field(description="查询起始日期 (YYYY-MM-DD)")
    end_date: str = Field(description="查询结束日期 (YYYY-MM-DD)")
    limit: int = Field(description="返回数量限制")
    offset: int = Field(description="结果偏移量")
    count: int = Field(description="实际返回数量")
    history: list[MacroTotalIndexHistoryItem] = Field(description="总指数历史序列")


# =============================
# A-Share basic info output models
# =============================


class StockBasicInfoItem(McpBaseModel):
    """A股股票基本信息。

    包含股票代码、名称、价格、市值、行业等基本信息，用于基本面分析的初始查询。
    """

    symbol: str = Field(description="股票代码 (如 '600519')")
    name: str = Field(description="股票名称 (如 '贵州茅台')")
    price: float = Field(description="当前价格")
    market_cap: float | None = Field(description="总市值", default=None)
    industry: str | None = Field(description="所属行业", default=None)
    listing_date: str | None = Field(description="上市日期 (YYYY-MM-DD)", default=None)


class StockBasicInfoResult(McpBaseModel):
    """A股股票基本信息查询结果。"""

    symbol: str = Field(description="查询的股票代码")
    info: StockBasicInfoItem = Field(description="股票基本信息")


class FinancialStatementItem(McpBaseModel):
    """财务报表单期数据 (整合资产负债/利润/现金流表核心字段)."""

    report_date: str = Field(description="报告期 (YYYY-MM-DD)")

    # 利润表
    revenue: float | None = Field(description="营业收入", default=None)
    net_profit: float | None = Field(description="净利润", default=None)
    net_profit_deduct_non_recurring: float | None = Field(description="扣非净利润", default=None)

    # 资产负债表
    total_assets: float | None = Field(description="总资产", default=None)
    total_liabilities: float | None = Field(description="总负债", default=None)
    total_equity: float | None = Field(description="股东权益", default=None)

    # 现金流量表
    operating_cash_flow: float | None = Field(description="经营活动现金流净额", default=None)
    investing_cash_flow: float | None = Field(description="投资活动现金流净额", default=None)
    financing_cash_flow: float | None = Field(description="筹资活动现金流净额", default=None)


class FinancialStatementsResult(McpBaseModel):
    """财务报表查询结果."""

    symbol: str = Field(description="股票代码")
    period: str = Field(description="周期类型 (report/yearly)")
    count: int = Field(description="返回期数")
    statements: list[FinancialStatementItem] = Field(description="报表数据列表")


class FinancialMetricItem(McpBaseModel):
    """财务指标数据."""

    report_date: str = Field(description="报告期 (YYYY-MM-DD)")
    eps: float | None = Field(description="每股收益 (EPS)", default=None)
    bvps: float | None = Field(description="每股净资产 (BPS)", default=None)
    pe: float | None = Field(description="市盈率 (PE)", default=None)
    pb: float | None = Field(description="市净率 (PB)", default=None)
    roe: float | None = Field(description="净资产收益率 (ROE)", default=None)
    gross_margin: float | None = Field(description="毛利率 (%)", default=None)
    net_margin: float | None = Field(description="净利率 (%)", default=None)
    debt_to_asset_ratio: float | None = Field(description="资产负债率 (%)", default=None)


class FinancialMetricsResult(McpBaseModel):
    """财务指标查询结果."""

    symbol: str = Field(description="股票代码")
    count: int = Field(description="返回期数")
    metrics: list[FinancialMetricItem] = Field(description="财务指标列表")


class ShareholderItem(McpBaseModel):
    """股东信息."""

    holder_name: str = Field(description="股东名称")
    hold_num: float | None = Field(description="持股数量", default=None)
    hold_ratio: float | None = Field(description="持股比例 (%)", default=None)
    nature: str | None = Field(description="股份性质", default=None)


class ShareholderInfoResult(McpBaseModel):
    """股东信息查询结果."""

    symbol: str = Field(description="股票代码")
    report_date: str | None = Field(description="最新报告期", default=None)
    holder_count: int | None = Field(description="股东总户数", default=None)
    avg_hold_num: float | None = Field(description="户均持股数", default=None)
    top_holders: list[ShareholderItem] = Field(description="前十大股东列表", default_factory=list)


class DividendItem(McpBaseModel):
    """分红记录."""

    report_date: str = Field(description="报告期")
    plan: str = Field(description="分红方案 (如 '10派10元')")
    register_date: str | None = Field(description="股权登记日", default=None)
    ex_date: str | None = Field(description="除权除息日", default=None)
    payment_date: str | None = Field(description="派息日", default=None)
    dividend_ratio: float | None = Field(description="股息率 (%)", default=None)


class DividendHistoryResult(McpBaseModel):
    """分红历史查询结果."""

    symbol: str = Field(description="股票代码")
    count: int = Field(description="记录数")
    history: list[DividendItem] = Field(description="历史分红列表")


class AnalystRatingItem(McpBaseModel):
    """分析师评级."""

    date: str = Field(description="评级日期")
    org_name: str = Field(description="机构名称")
    analyst: str | None = Field(description="分析师", default=None)
    rating: str = Field(description="评级 (如 '买入', '增持')")
    target_price: float | None = Field(description="目标价", default=None)


class AnalystConsensusResult(McpBaseModel):
    """分析师一致预期查询结果."""

    symbol: str = Field(description="股票代码")
    target_price: float | None = Field(description="一致目标价", default=None)
    rating_buy: int | None = Field(description="买入评级数", default=None)
    rating_overweight: int | None = Field(description="增持评级数", default=None)
    rating_hold: int | None = Field(description="中性评级数", default=None)
    rating_sell: int | None = Field(description="卖出评级数", default=None)
    rating_underweight: int | None = Field(description="减持评级数", default=None)
    latest_ratings: list[AnalystRatingItem] = Field(description="近期评级列表", default_factory=list)


class MacroIndicatorItem(McpBaseModel):
    """宏观指标数据."""

    name: str = Field(description="指标名称 (中文)")
    value: float | None = Field(description="数值")
    unit: str | None = Field(description="单位", default=None)
    date: str = Field(description="发布日期/数据日期")


class MacroIndicatorsResult(McpBaseModel):
    """宏观数据查询结果."""

    category: str = Field(description="数据类别")
    count: int = Field(description="返回指标数")
    indicators: list[MacroIndicatorItem] = Field(description="指标列表")


# =============================
# Calendar output models
# =============================


class EconomicCalendarItem(McpBaseModel):
    """财经日历事件项.

    包含经济指标发布、央行决议等财经事件信息.
    """

    date: str = Field(description="事件日期 (YYYY-MM-DD)")
    time: str = Field(description="事件时间 (HH:MM)")
    country: str = Field(description="国家/地区")
    event: str = Field(description="事件名称")
    actual: str | None = Field(description="实际公布值", default=None)
    forecast: str | None = Field(description="预期值", default=None)
    previous: str | None = Field(description="前值", default=None)
    importance: int = Field(description="重要性等级 (1-3, 3为最高)")


class EconomicCalendarResult(McpBaseModel):
    """财经日历查询结果.

    返回指定日期范围内的财经事件列表.
    """

    start_date: str = Field(description="查询起始日期 (YYYY-MM-DD)")
    end_date: str = Field(description="查询结束日期 (YYYY-MM-DD)")
    count: int = Field(description="事件总数")
    events: list[EconomicCalendarItem] = Field(description="财经事件列表")


class EarningsCalendarItem(McpBaseModel):
    """财报日历事件项.

    包含美股、港股、A股的财报发布信息.
    """

    symbol: str = Field(description="股票代码")
    name: str = Field(description="公司名称")
    exchange: str = Field(description="交易所 (US/HK/SH/SZ)")
    report_type: str = Field(description="财报类型")
    release_time: str = Field(description="发布时间说明 (盘前/盘后/--)")
    market_cap: int | None = Field(description="市值", default=None)
    report_date: str = Field(description="发布日期 (YYYY-MM-DD)")


class EarningsCalendarResult(McpBaseModel):
    """财报日历查询结果.

    返回指定日期范围内的财报发布列表.
    """

    start_date: str = Field(description="查询起始日期 (YYYY-MM-DD)")
    end_date: str = Field(description="查询结束日期 (YYYY-MM-DD)")
    count: int = Field(description="财报总数")
    earnings: list[EarningsCalendarItem] = Field(description="财报发布列表")
