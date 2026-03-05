import asyncio
import json
import logging
import os
import re
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal

import akshare as ak
import httpx
import pandas as pd
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field, ValidationError
from shared.database import session_scope
from shared.logging import configure_logging
from shared.models.macro import (
    MacroFactorSnapshot,
    MacroModuleHistory,
    MacroModuleSnapshot,
    MacroReport,
    MacroTotalIndexHistory,
)
from shared.models.news import NewsArticle
from shared.models.options import OptionsFlow
from sqlalchemy import func, select

from .schemas import (
    EarningsCalendarItem,
    EarningsCalendarResult,
    EconomicCalendarItem,
    EconomicCalendarResult,
    FinancialMetricItem,
    FinancialMetricsResult,
    FinancialStatementItem,
    FinancialStatementsResult,
    FlowSummaryResult,
    MacroFactorSnapshotItem,
    MacroFactorSnapshotsResult,
    MacroIndicatorItem,
    MacroIndicatorsResult,
    MacroModuleHistoryItem,
    MacroModuleHistoryResult,
    MacroModuleSnapshotItem,
    MacroModuleSnapshotsResult,
    MacroReportItem,
    MacroReportsResult,
    MacroTotalIndexHistoryItem,
    MacroTotalIndexHistoryResult,
    NewsArticleItem,
    NewsArticlesResult,
    NewsType,
    OptionsFlowItem,
    OptionsSide,
    OptionType,
    SideStats,
    StockBasicInfoItem,
    StockBasicInfoResult,
    StockHistoryResult,
    Timeframe,
    TopSymbol,
    TradingViewMarketSearchResult,
    TypeStats,
)

configure_logging(service="mcp-server")
logger = logging.getLogger(__name__)

mcp = FastMCP("Finance")


def get_stock_api_url() -> str:
    return os.getenv("FA_MCP_SERVER_STOCK_API_URL", "http://stock-api:3000")


def parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default

    normalized = value.strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def macro_protected_data_enabled() -> bool:
    return parse_bool(os.getenv("FA_MACRO_SCRAPER_ENABLE_PROTECTED_ENDPOINTS"), False)


MACRO_PROTECTED_TOOLS_ENABLED = macro_protected_data_enabled()


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ToolError(f"日期格式错误: {value}") from exc


def resolve_date_range(days: int | None, start_date: str | None, end_date: str | None) -> tuple[date, date]:
    today = datetime.now(tz=UTC).date()
    if start_date:
        start = parse_iso_date(start_date)
        end = parse_iso_date(end_date) if end_date else today
    else:
        if days is None:
            raise ToolError("days 不能为空")
        end = parse_iso_date(end_date) if end_date else today
        start = end - timedelta(days=days)

    if start > end:
        raise ToolError("start_date 不能晚于 end_date")
    return start, end


def resolve_optional_date_range(
    days: int | None,
    start_date: str | None,
    end_date: str | None,
) -> tuple[date | None, date | None]:
    if days is None and start_date is None and end_date is None:
        return None, None

    today = datetime.now(tz=UTC).date()
    end = parse_iso_date(end_date) if end_date else today

    if start_date:
        start = parse_iso_date(start_date)
    elif days is not None:
        start = end - timedelta(days=days)
    else:
        start = None

    if start and start > end:
        raise ToolError("start_date 不能晚于 end_date")

    return start, end


def normalize_hk_stock_code(stock: str) -> str:
    code = stock.strip().upper()
    if code.endswith(".HK"):
        code = code[:-3]
    digits = "".join(ch for ch in code if ch.isdigit())
    if digits:
        return digits.zfill(5)
    return code


def _find_date_column(
    df: pd.DataFrame,
    preferred: tuple[str, ...] = (),
) -> str | None:
    for preferred_name in preferred:
        if preferred_name in df.columns:
            return preferred_name

    date_keywords = ("日期", "date", "月份", "month", "时间", "发布")
    for column in df.columns:
        name = str(column).lower()
        if any(keyword in name for keyword in date_keywords):
            return str(column)
    return str(df.columns[0]) if len(df.columns) else None


def _find_value_column(
    df: pd.DataFrame,
    date_column: str | None,
    preferred: tuple[str, ...] = (),
) -> str | None:
    priority_keywords = (
        "今值",
        "现值",
        "value",
        "数值",
        "指数值",
        "指数",
        "失业率",
        "lpr1y",
        "lpr5y",
        "社会融资规模增量",
    )

    def is_numeric_column(series: pd.Series) -> bool:
        if pd.api.types.is_numeric_dtype(series):
            return True
        converted = pd.to_numeric(series, errors="coerce")
        return converted.notna().sum() > 0

    candidates = [c for c in df.columns if str(c) != str(date_column)]
    if not candidates:
        return None

    for preferred_name in preferred:
        for column in candidates:
            if str(column) == preferred_name and is_numeric_column(df[column]):
                return str(column)

    for preferred_name in preferred:
        for column in candidates:
            if preferred_name in str(column) and is_numeric_column(df[column]):
                return str(column)

    for keyword in priority_keywords:
        for column in candidates:
            if keyword in str(column).lower() and is_numeric_column(df[column]):
                return str(column)

    for column in candidates:
        if pd.api.types.is_numeric_dtype(df[column]):
            return str(column)

    best_column: str | None = None
    best_count = -1
    for column in candidates:
        converted = pd.to_numeric(df[column], errors="coerce")
        count = int(converted.notna().sum())
        if count > best_count:
            best_count = count
            best_column = str(column)
    return best_column


def _parse_macro_date_value(value: Any) -> datetime | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())

    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return None

    direct_formats = ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d")
    for fmt in direct_formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass

    month_match = re.match(r"^(\d{4})(\d{2})$", text)
    if month_match:
        year, month = int(month_match.group(1)), int(month_match.group(2))
        if 1 <= month <= 12:
            return datetime(year, month, 1)

    zh_month_match = re.match(r"^(\d{4})年(\d{1,2})月(?:份)?$", text)
    if zh_month_match:
        year, month = int(zh_month_match.group(1)), int(zh_month_match.group(2))
        if 1 <= month <= 12:
            return datetime(year, month, 1)

    quarter_range_match = re.match(r"^(\d{4})年第1-([1-4])季度$", text)
    if quarter_range_match:
        year = int(quarter_range_match.group(1))
        month = int(quarter_range_match.group(2)) * 3
        return datetime(year, month, 1)

    quarter_match = re.match(r"^(\d{4})(?:年)?第([1-4])季度$", text)
    if quarter_match:
        year = int(quarter_match.group(1))
        month = int(quarter_match.group(2)) * 3
        return datetime(year, month, 1)

    fallback = pd.to_datetime(text, errors="coerce")
    if pd.notna(fallback):
        return fallback.to_pydatetime()
    return None


def _parse_macro_dates(series: pd.Series) -> pd.Series:
    parsed = [_parse_macro_date_value(value) for value in series]
    return pd.to_datetime(parsed, errors="coerce")


def _normalize_macro_latest(
    df: pd.DataFrame,
    *,
    start: date | None,
    end: date | None,
    date_candidates: tuple[str, ...] = (),
    value_candidates: tuple[str, ...] = (),
    item_filter: tuple[str, str] | None = None,
) -> tuple[pd.Series, str | None, str | None]:
    data = df.copy().reset_index(drop=True)

    if item_filter:
        item_column, item_value = item_filter
        if item_column in data.columns:
            data = data[data[item_column].astype(str) == item_value]
            if data.empty:
                raise ValueError(f"按 {item_column}={item_value} 过滤后无数据")

    date_column = _find_date_column(data, preferred=date_candidates)
    if date_column and date_column in data.columns:
        parsed_dates = _parse_macro_dates(data[date_column])
    else:
        parsed_dates = pd.Series([pd.NaT] * len(data), index=data.index)

    data = data.assign(_parsed_date=parsed_dates, _origin_order=data.index)

    if data["_parsed_date"].notna().any() and (start is not None or end is not None):
        if start is not None:
            start_ts = pd.Timestamp(start)
            data = data[data["_parsed_date"] >= start_ts]
        if end is not None:
            end_ts = pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
            data = data[data["_parsed_date"] <= end_ts]
        if data.empty:
            raise ValueError("时间范围内无数据")

    value_column = _find_value_column(data, date_column, preferred=value_candidates)
    if not value_column:
        raise ValueError("未识别到可用数值列")

    numeric_values = pd.to_numeric(data[value_column], errors="coerce")
    candidates = data.assign(_numeric_value=numeric_values)
    candidates = candidates[candidates["_numeric_value"].notna()]
    if candidates.empty:
        raise ValueError(f"列 {value_column} 在时间范围内均为空")

    if candidates["_parsed_date"].notna().any():
        candidates = candidates.sort_values(
            ["_parsed_date", "_origin_order"],
            ascending=[False, False],
            na_position="last",
        )
    else:
        candidates = candidates.sort_values("_origin_order", ascending=False)

    latest = candidates.iloc[0]
    return latest, date_column, value_column


def _format_date_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)


@mcp.tool(annotations={"readOnlyHint": True})
async def query_news_articles(
    days: Annotated[
        int,
        Field(
            description="查询最近N天的新闻",
            ge=1,
            le=365,
        ),
    ] = 7,
    symbols: Annotated[
        list[str] | None,
        Field(description=("股票代码列表（不带交易所前缀），如 ['AAPL', 'TSLA']。用于过滤新闻。")),
    ] = None,
    type: Annotated[
        NewsType | None,
        Field(
            description=(
                "新闻类型过滤: 'macro_news' (宏观新闻), 'kol_tweet' (KOL推文), "
                "'stock_news' (个股新闻)。留空则返回所有类型"
            )
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            description="返回结果数量限制",
            ge=1,
            le=500,
        ),
    ] = 50,
    offset: Annotated[
        int,
        Field(
            description="结果偏移量，用于分页",
            ge=0,
        ),
    ] = 0,
) -> NewsArticlesResult:
    """查询新闻文章数据.

    支持按照时间范围、股票代码、新闻类型进行过滤，并支持分页。
    返回结果按发布时间降序排列 (最新的在前)。
    """

    since = datetime.now(tz=UTC) - timedelta(days=days)

    stmt = select(NewsArticle).where(NewsArticle.published_at >= since)

    if type:
        stmt = stmt.where(NewsArticle.type == type)

    if symbols:
        normalized_symbols = [s.strip().upper() for s in symbols if s.strip()]
        if normalized_symbols:
            stmt = stmt.where(NewsArticle.symbols.overlap(normalized_symbols))

    stmt = stmt.order_by(NewsArticle.published_at.desc()).offset(offset).limit(limit)

    async with session_scope() as session:
        result = await session.execute(stmt)
        rows = result.scalars().all()

    return NewsArticlesResult(
        since=since.isoformat(),
        limit=limit,
        offset=offset,
        count=len(rows),
        articles=[
            NewsArticleItem(
                external_id=row.external_id,
                type=row.type,
                source=row.source,
                news_title=row.title or "",
                url=row.url or "",
                author=row.author,
                symbols=row.symbols or [],
                tags=row.tags or [],
                importance=row.importance,
                published_at=row.published_at.isoformat(),
            )
            for row in rows
        ],
    )


async def query_macro_reports(
    days: Annotated[
        int,
        Field(
            description="查询最近N天的宏观报告",
            ge=1,
            le=3650,
        ),
    ] = 90,
    start_date: Annotated[
        str | None,
        Field(
            description="起始日期 (YYYY-MM-DD)。提供后将忽略 days",
        ),
    ] = None,
    end_date: Annotated[
        str | None,
        Field(description="结束日期 (YYYY-MM-DD)，留空则为今天"),
    ] = None,
    limit: Annotated[
        int,
        Field(
            description="返回结果数量限制",
            ge=1,
            le=500,
        ),
    ] = 100,
    offset: Annotated[
        int,
        Field(
            description="结果偏移量，用于分页",
            ge=0,
        ),
    ] = 0,
) -> MacroReportsResult:
    """查询 The Dial 宏观报告快照。

    报告包含总指数评分、对比变化与生成时间，是宏观环境的“总览快照”。
    适用于快速回顾宏观风险趋势或作为深入查询模块/因子的入口。
    返回结果按报告日期降序排列 (最新的在前)。
    """

    start, end = resolve_date_range(days, start_date, end_date)

    stmt = (
        select(MacroReport)
        .where(MacroReport.report_date >= start)
        .where(MacroReport.report_date <= end)
        .order_by(MacroReport.report_date.desc())
        .offset(offset)
        .limit(limit)
    )

    async with session_scope() as session:
        result = await session.execute(stmt)
        rows = result.scalars().all()

    return MacroReportsResult(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        limit=limit,
        offset=offset,
        count=len(rows),
        reports=[
            MacroReportItem(
                report_date=row.report_date.isoformat(),
                current_snapshot_date=(row.current_snapshot_date.isoformat() if row.current_snapshot_date else None),
                compare_date=(row.compare_date.isoformat() if row.compare_date else None),
                generated_at=(row.generated_at.isoformat() if row.generated_at else None),
                current_score=row.current_score,
                compare_score=row.compare_score,
                change=row.change,
                change_pct=row.change_pct,
            )
            for row in rows
        ],
    )


if MACRO_PROTECTED_TOOLS_ENABLED:
    mcp.tool(annotations={"readOnlyHint": True})(query_macro_reports)


async def query_macro_module_snapshots(
    module_id: Annotated[
        str | None,
        Field(description="模块ID (如 liquidity, rates)，留空则返回所有模块"),
    ] = None,
    days: Annotated[
        int,
        Field(
            description="查询最近N天的模块快照",
            ge=1,
            le=3650,
        ),
    ] = 30,
    start_date: Annotated[
        str | None,
        Field(description="起始日期 (YYYY-MM-DD)。提供后将忽略 days"),
    ] = None,
    end_date: Annotated[
        str | None,
        Field(description="结束日期 (YYYY-MM-DD)，留空则为今天"),
    ] = None,
    limit: Annotated[
        int,
        Field(
            description="返回结果数量限制",
            ge=1,
            le=1000,
        ),
    ] = 200,
    offset: Annotated[
        int,
        Field(
            description="结果偏移量，用于分页",
            ge=0,
        ),
    ] = 0,
) -> MacroModuleSnapshotsResult:
    """查询宏观模块快照。

    模块快照提供 The Dial 各宏观模块（如流动性、利率、风险偏好等）
    在每个报告日的评分与变化，用于比较不同模块的相对强弱。
    返回结果按报告日期降序排列 (最新的在前)。
    """

    start, end = resolve_date_range(days, start_date, end_date)

    stmt = (
        select(MacroModuleSnapshot)
        .where(MacroModuleSnapshot.report_date >= start)
        .where(MacroModuleSnapshot.report_date <= end)
    )
    if module_id:
        stmt = stmt.where(MacroModuleSnapshot.module_id == module_id.strip())

    stmt = (
        stmt.order_by(
            MacroModuleSnapshot.report_date.desc(),
            MacroModuleSnapshot.module_id.asc(),
        )
        .offset(offset)
        .limit(limit)
    )

    async with session_scope() as session:
        result = await session.execute(stmt)
        rows = result.scalars().all()

    return MacroModuleSnapshotsResult(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        limit=limit,
        offset=offset,
        count=len(rows),
        modules=[
            MacroModuleSnapshotItem(
                report_date=row.report_date.isoformat(),
                module_id=row.module_id,
                name=row.name,
                name_cn=row.name_cn,
                current_score=row.current_score,
                compare_score=row.compare_score,
                change=row.change,
                change_pct=row.change_pct,
            )
            for row in rows
        ],
    )


if MACRO_PROTECTED_TOOLS_ENABLED:
    mcp.tool(annotations={"readOnlyHint": True})(query_macro_module_snapshots)


async def query_macro_factor_snapshots(
    module_id: Annotated[
        str | None,
        Field(description="模块ID (如 liquidity)，留空则返回所有模块"),
    ] = None,
    factor_id: Annotated[
        str | None,
        Field(description="因子ID (如 vix, sofr)，留空则返回所有因子"),
    ] = None,
    display_only: Annotated[
        bool | None,
        Field(description="仅返回展示型因子 (不参与评分)。留空则不过滤"),
    ] = None,
    days: Annotated[
        int,
        Field(
            description="查询最近N天的因子快照",
            ge=1,
            le=3650,
        ),
    ] = 30,
    start_date: Annotated[
        str | None,
        Field(description="起始日期 (YYYY-MM-DD)。提供后将忽略 days"),
    ] = None,
    end_date: Annotated[
        str | None,
        Field(description="结束日期 (YYYY-MM-DD)，留空则为今天"),
    ] = None,
    limit: Annotated[
        int,
        Field(
            description="返回结果数量限制",
            ge=1,
            le=1000,
        ),
    ] = 200,
    offset: Annotated[
        int,
        Field(
            description="结果偏移量，用于分页",
            ge=0,
        ),
    ] = 0,
) -> MacroFactorSnapshotsResult:
    """查询宏观因子快照。

    因子是驱动模块变化的具体指标（如 SOFR、VIX、美元指数等）。
    该查询提供当前值、分位和对比变化，便于定位模块评分变化的来源。
    返回结果按报告日期降序排列 (最新的在前)。
    """

    start, end = resolve_date_range(days, start_date, end_date)

    stmt = (
        select(MacroFactorSnapshot)
        .where(MacroFactorSnapshot.report_date >= start)
        .where(MacroFactorSnapshot.report_date <= end)
    )
    if module_id:
        stmt = stmt.where(MacroFactorSnapshot.module_id == module_id.strip())
    if factor_id:
        stmt = stmt.where(MacroFactorSnapshot.factor_id == factor_id.strip())
    if display_only is not None:
        stmt = stmt.where(MacroFactorSnapshot.display_only == display_only)

    stmt = (
        stmt.order_by(
            MacroFactorSnapshot.report_date.desc(),
            MacroFactorSnapshot.module_id.asc(),
            MacroFactorSnapshot.factor_id.asc(),
        )
        .offset(offset)
        .limit(limit)
    )

    async with session_scope() as session:
        result = await session.execute(stmt)
        rows = result.scalars().all()

    return MacroFactorSnapshotsResult(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        limit=limit,
        offset=offset,
        count=len(rows),
        factors=[
            MacroFactorSnapshotItem(
                report_date=row.report_date.isoformat(),
                module_id=row.module_id,
                module_name=row.module_name,
                module_name_cn=row.module_name_cn,
                factor_id=row.factor_id,
                name=row.name,
                name_cn=row.name_cn,
                display_only=row.display_only,
                current_value=row.current_value,
                current_value_formatted=row.current_value_formatted,
                current_percentile=row.current_percentile,
                compare_value=row.compare_value,
                compare_value_formatted=row.compare_value_formatted,
                compare_percentile=row.compare_percentile,
                value_change=row.value_change,
                value_change_pct=row.value_change_pct,
                percentile_change=row.percentile_change,
                percentile_change_pct=row.percentile_change_pct,
                color=row.color,
            )
            for row in rows
        ],
    )


if MACRO_PROTECTED_TOOLS_ENABLED:
    mcp.tool(annotations={"readOnlyHint": True})(query_macro_factor_snapshots)


@mcp.tool(annotations={"readOnlyHint": True})
async def query_macro_module_history(
    module_id: Annotated[
        str,
        Field(description="模块ID (如 liquidity, funding, rates)", min_length=1),
    ],
    days: Annotated[
        int,
        Field(
            description="查询最近N天的模块评分序列",
            ge=1,
            le=3650,
        ),
    ] = 365,
    start_date: Annotated[
        str | None,
        Field(description="起始日期 (YYYY-MM-DD)。提供后将忽略 days"),
    ] = None,
    end_date: Annotated[
        str | None,
        Field(description="结束日期 (YYYY-MM-DD)，留空则为今天"),
    ] = None,
    limit: Annotated[
        int,
        Field(
            description="返回结果数量限制",
            ge=1,
            le=10000,
        ),
    ] = 2000,
    offset: Annotated[
        int,
        Field(
            description="结果偏移量，用于分页",
            ge=0,
        ),
    ] = 0,
) -> MacroModuleHistoryResult:
    """查询宏观模块评分的历史时间序列。

    该接口用于分析某一模块在时间维度的趋势与拐点，
    适合用于回测或与价格/风险指标进行对比分析。
    返回结果按日期升序排列 (最早的在前)。
    """

    start, end = resolve_date_range(days, start_date, end_date)

    stmt = (
        select(MacroModuleHistory)
        .where(MacroModuleHistory.module_id == module_id.strip())
        .where(MacroModuleHistory.date >= start)
        .where(MacroModuleHistory.date <= end)
        .order_by(MacroModuleHistory.date.asc())
        .offset(offset)
        .limit(limit)
    )

    async with session_scope() as session:
        result = await session.execute(stmt)
        rows = result.scalars().all()

    return MacroModuleHistoryResult(
        module_id=module_id.strip(),
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        limit=limit,
        offset=offset,
        count=len(rows),
        history=[
            MacroModuleHistoryItem(
                date=row.date.isoformat(),
                module_id=row.module_id,
                module_name=row.module_name,
                module_name_cn=row.module_name_cn,
                value=row.value,
                percentile=row.percentile,
            )
            for row in rows
        ],
    )


@mcp.tool(annotations={"readOnlyHint": True})
async def query_macro_total_index_history(
    days: Annotated[
        int,
        Field(
            description="查询最近N天的总指数序列",
            ge=1,
            le=3650,
        ),
    ] = 365,
    start_date: Annotated[
        str | None,
        Field(description="起始日期 (YYYY-MM-DD)。提供后将忽略 days"),
    ] = None,
    end_date: Annotated[
        str | None,
        Field(description="结束日期 (YYYY-MM-DD)，留空则为今天"),
    ] = None,
    limit: Annotated[
        int,
        Field(
            description="返回结果数量限制",
            ge=1,
            le=10000,
        ),
    ] = 2000,
    offset: Annotated[
        int,
        Field(
            description="结果偏移量，用于分页",
            ge=0,
        ),
    ] = 0,
) -> MacroTotalIndexHistoryResult:
    """查询宏观总指数的历史时间序列。

    总指数反映整体宏观环境的风险/流动性状态，
    可用于与市场波动、资金流向等指标进行综合对比分析。
    返回结果按日期升序排列 (最早的在前)。
    """

    start, end = resolve_date_range(days, start_date, end_date)

    stmt = (
        select(MacroTotalIndexHistory)
        .where(MacroTotalIndexHistory.date >= start)
        .where(MacroTotalIndexHistory.date <= end)
        .order_by(MacroTotalIndexHistory.date.asc())
        .offset(offset)
        .limit(limit)
    )

    async with session_scope() as session:
        result = await session.execute(stmt)
        rows = result.scalars().all()

    return MacroTotalIndexHistoryResult(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        limit=limit,
        offset=offset,
        count=len(rows),
        history=[
            MacroTotalIndexHistoryItem(
                date=row.date.isoformat(),
                value=row.value,
                percentile=row.percentile,
            )
            for row in rows
        ],
    )


async def fetch_stock_api_json(path: str, params: dict[str, str]) -> dict[str, Any]:
    url = get_stock_api_url().rstrip("/") + path
    timeout = httpx.Timeout(30.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.get(url, params=params)
        except Exception as exc:
            raise ToolError(f"请求 stock-api 失败: {str(exc)}") from exc

        try:
            payload = resp.json()
        except Exception:
            payload = None

        if resp.is_error:
            detail: str | None = None
            if isinstance(payload, dict):
                value = payload.get("error")
                if isinstance(value, str) and value.strip():
                    detail = value.strip()

            if detail:
                raise ToolError(f"stock-api 请求失败 (HTTP {resp.status_code}): {detail}")

            body = resp.text.strip()
            if len(body) > 1000:
                body = body[:1000] + "..."
            raise ToolError(f"stock-api 请求失败 (HTTP {resp.status_code}): {body or resp.reason_phrase}")

        if not isinstance(payload, dict):
            raise ToolError("stock-api 返回格式不符合预期: 不是 JSON object")

        return payload


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_market(
    query: Annotated[
        str,
        Field(
            description=(
                "搜索关键词。支持 ticker、公司名或 'EXCHANGE:' 前缀提示。示例：'WMT'、'walmart'、'NASDAQ:'、'BINANCE:'."
            ),
            min_length=1,
        ),
    ],
    type: Annotated[
        Literal["stock", "futures", "forex", "cfd", "crypto", "index", "economic"] | None,
        Field(description=("市场类型过滤。留空则不过滤。可选：stock/futures/forex/cfd/crypto/index/economic")),
    ] = "stock",
    limit: Annotated[
        int,
        Field(
            description="返回候选数量上限",
            ge=1,
            le=50,
        ),
    ] = 10,
    offset: Annotated[
        int,
        Field(
            description="分页偏移 (start)",
            ge=0,
            le=10000,
        ),
    ] = 0,
) -> TradingViewMarketSearchResult:
    """根据关键词返回候选 market id 列表。

    推荐工作流：
    1) 调用本工具用 ticker/公司名搜索，得到候选的 `id`（形如 `NASDAQ:AAPL`）
    2) 将 `id` 传给 `fetch_stock_history.symbol` 获取历史 K 线
    """

    params: dict[str, str] = {
        "q": query,
        "limit": str(limit),
        "offset": str(offset),
    }
    if type is not None:
        params["type"] = type

    try:
        payload = await fetch_stock_api_json("/v0/searchMarket", params)
        return TradingViewMarketSearchResult.model_validate(payload, extra="ignore")
    except ValidationError as exc:
        raise ToolError(f"stock-api 返回格式不符合预期: {exc}") from exc


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def fetch_stock_history(
    symbol: Annotated[
        str,
        Field(
            description=(
                "TradingView market id，格式为 'EXCHANGE:SYMBOL'。"
                "如果你不确定交易所前缀（尤其是标的迁移/新标的），请先调用 `search_market` 搜索得到正确的 market id。"
                "示例：NASDAQ:AAPL、NYSE:BRK.B、SSE:000001、SZSE:000001、HKEX:700、BINANCE:BTCUSDT"
            ),
            min_length=1,
            pattern=r"^[^\s:]+:[^\s:]+$",
        ),
    ],
    timeframe: Annotated[
        Timeframe,
        Field(
            description=(
                "时间周期, 单位是分钟，D/W/M 分别为日/周/月: "
                "'1','3','5','15','30','45','60','120','180','240','D','W','M'"
            )
        ),
    ] = "D",
    range: Annotated[
        int,
        Field(
            description="返回K线数据点数量",
            ge=1,
            le=5000,
        ),
    ] = 200,
    to: Annotated[
        int | None,
        Field(
            description="结束时间戳 (Unix timestamp, 秒)。留空则使用当前时间",
            ge=1,
        ),
    ] = None,
) -> StockHistoryResult:
    """从 stock-api 获取股票历史 K 线数据 (OHLCV).

    该工具通过 HTTP 调用内部 `stock-api` 服务，返回 K 线数据。
    返回结果按时间降序排列 (最新的在前)。

    注意：为避免同名 ticker 查错，本工具强制要求 `symbol` 使用 TradingView market id
    形式 `EXCHANGE:SYMBOL`。如果不确定交易所前缀，请先调用 `search_market`
    搜索得到正确的 market id。
    """

    params: dict[str, str] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "range": str(range),
    }
    if to is not None:
        params["to"] = str(to)

    try:
        payload = await fetch_stock_api_json("/history", params)
        return StockHistoryResult.model_validate(payload, extra="ignore")
    except ValidationError as exc:
        raise ToolError(f"stock-api 返回格式不符合预期: {exc}") from exc
    except ToolError as exc:
        msg = str(exc)
        if "Failed to load chart for" in msg or "HTTP 404" in msg:
            raise ToolError(
                msg
                + "\n\n可能原因：交易所前缀错误或 market id 不存在。"
                + "建议：先调用 `search_market(query=...)` 查到正确的 TradingView market id，"
                + "再调用 `fetch_stock_history`。"
            ) from exc
        raise
    except Exception as exc:
        raise ToolError(f"获取股票历史数据失败: {str(exc)}") from exc


# @mcp.tool()
async def fetch_indicator(
    symbol: str,
    indicator_id: str,
    timeframe: str = "D",
    range: int = 200,
    to: int | None = None,
    options: dict[str, Any] | None = None,
) -> str:
    params: dict[str, str] = {
        "symbol": symbol,
        "indicatorId": indicator_id,
        "timeframe": timeframe,
        "range": str(range),
    }
    if to is not None:
        params["to"] = str(to)
    if options is not None:
        params["options"] = json.dumps(options)

    try:
        payload = await fetch_stock_api_json("/indicator", params)
        return json.dumps(payload, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, indent=2)


# @mcp.tool()
async def fetch_technical_analysis(symbol: str) -> str:
    try:
        payload = await fetch_stock_api_json("/ta", {"symbol": symbol})
        return json.dumps(payload, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, indent=2)


# @mcp.tool()
async def list_private_indicators() -> str:
    try:
        payload = await fetch_stock_api_json("/indicators/private", {})
        return json.dumps(payload, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, indent=2)


@mcp.tool(annotations={"readOnlyHint": True})
async def query_options_flow(
    symbol: Annotated[
        str | None,
        Field(description=("股票代码（不带交易所前缀），如 'BSX', 'AAPL'。用于过滤期权流。")),
    ] = None,
    side: Annotated[
        OptionsSide | None,
        Field(description="交易方向。'Bid' = 买方主动成交, 'Ask' = 卖方主动成交"),
    ] = None,
    option_type: Annotated[
        OptionType | None,
        Field(description="期权类型。'P' = Put (看跌), 'C' = Call (看涨)"),
    ] = None,
    days: Annotated[
        int,
        Field(
            description="查询最近N天的数据",
            ge=1,
            le=365,
        ),
    ] = 7,
    min_premium: Annotated[
        float | None,
        Field(
            description="最小权利金过滤 (美元)，用于筛选大单",
            ge=0,
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            description="返回结果数量限制",
            ge=1,
            le=1000,
        ),
    ] = 50,
) -> list[OptionsFlowItem]:
    """查询期权大单流向数据.

    支持按标的、方向、期权类型、时间范围、最小权利金等条件过滤。
    返回结果按时间降序排列 (最新的在前)。
    """

    since = datetime.now(tz=UTC) - timedelta(days=days)

    stmt = select(OptionsFlow).where(OptionsFlow.timestamp >= since)

    if symbol:
        stmt = stmt.where(OptionsFlow.symbol == symbol.strip().upper())
    if side:
        stmt = stmt.where(OptionsFlow.side == side)
    if option_type:
        stmt = stmt.where(OptionsFlow.option_type == option_type)
    if min_premium is not None:
        stmt = stmt.where(OptionsFlow.premium >= min_premium)

    stmt = stmt.order_by(OptionsFlow.timestamp.desc()).limit(limit)

    async with session_scope() as session:
        result = await session.execute(stmt)
        rows = result.scalars().all()

    return [
        OptionsFlowItem(
            timestamp=row.timestamp.isoformat(),
            symbol=row.symbol,
            strike=row.strike,
            option_type=row.option_type,
            expiry=row.expiry.isoformat(),
            dte=row.dte,
            side=row.side,
            interval_volume=row.interval_volume,
            open_interest=row.open_interest,
            vol_oi=row.vol_oi,
            otm_percent=row.otm_percent,
            bid_percent=row.bid_percent,
            ask_percent=row.ask_percent,
            premium=row.premium,
            avg_fill=row.avg_fill,
            multileg_percent=row.multileg_percent,
        )
        for row in rows
    ]


@mcp.tool(annotations={"readOnlyHint": True})
async def get_flow_summary(
    days: Annotated[
        int,
        Field(
            description="统计最近N天的数据",
            ge=1,
            le=365,
        ),
    ] = 1,
) -> FlowSummaryResult:
    """获取期权流向汇总统计.

    汇总指定时间范围内的交易数、权利金，并按方向/类型聚合，返回 Top 标的。
    """

    since = datetime.now(tz=UTC) - timedelta(days=days)

    async with session_scope() as session:
        total_stmt = select(
            func.count(OptionsFlow.id).label("count"),
            func.sum(OptionsFlow.premium).label("total_premium"),
        ).where(OptionsFlow.timestamp >= since)
        total = (await session.execute(total_stmt)).one()

        by_side_stmt = (
            select(
                OptionsFlow.side,
                func.count(OptionsFlow.id).label("count"),
                func.sum(OptionsFlow.premium).label("premium"),
            )
            .where(OptionsFlow.timestamp >= since)
            .group_by(OptionsFlow.side)
        )
        by_side = (await session.execute(by_side_stmt)).all()

        by_type_stmt = (
            select(
                OptionsFlow.option_type,
                func.count(OptionsFlow.id).label("count"),
                func.sum(OptionsFlow.premium).label("premium"),
            )
            .where(OptionsFlow.timestamp >= since)
            .group_by(OptionsFlow.option_type)
        )
        by_type = (await session.execute(by_type_stmt)).all()

        top_symbols_stmt = (
            select(
                OptionsFlow.symbol,
                func.count(OptionsFlow.id).label("count"),
                func.sum(OptionsFlow.premium).label("total_premium"),
            )
            .where(OptionsFlow.timestamp >= since)
            .group_by(OptionsFlow.symbol)
            .order_by(func.sum(OptionsFlow.premium).desc())
            .limit(10)
        )
        top_symbols = (await session.execute(top_symbols_stmt)).all()

    return FlowSummaryResult(
        period_days=days,
        total_trades=total.count or 0,
        total_premium=float(total.total_premium or 0),
        by_side={row.side: SideStats(count=row.count, premium=float(row.premium or 0)) for row in by_side},
        by_type={row.option_type: TypeStats(count=row.count, premium=float(row.premium or 0)) for row in by_type},
        top_symbols=[
            TopSymbol(
                symbol=row.symbol,
                count=row.count,
                premium=float(row.total_premium or 0),
            )
            for row in top_symbols
        ],
    )


@mcp.tool(annotations={"readOnlyHint": True})
async def get_unusual_activity(
    days: Annotated[
        int,
        Field(
            description="查询最近N天",
            ge=1,
            le=365,
        ),
    ] = 1,
    min_vol_oi: Annotated[
        float,
        Field(
            description="最小成交量/未平仓量比率 (Vol/OI)。高比率表示异常活跃",
            ge=0,
        ),
    ] = 5.0,
    limit: Annotated[
        int,
        Field(
            description="返回结果数量",
            ge=1,
            le=500,
        ),
    ] = 20,
) -> list[OptionsFlowItem]:
    """获取异常期权活动 (高 Vol/OI 比率).

    返回结果按 Vol/OI 降序排列 (最异常的在前)。
    """

    since = datetime.now(tz=UTC) - timedelta(days=days)

    stmt = (
        select(OptionsFlow)
        .where(OptionsFlow.timestamp >= since)
        .where(OptionsFlow.vol_oi >= min_vol_oi)
        .order_by(OptionsFlow.vol_oi.desc())
        .limit(limit)
    )

    async with session_scope() as session:
        result = await session.execute(stmt)
        rows = result.scalars().all()

    return [
        OptionsFlowItem(
            timestamp=row.timestamp.isoformat(),
            symbol=row.symbol,
            strike=row.strike,
            option_type=row.option_type,
            expiry=row.expiry.isoformat(),
            dte=row.dte,
            side=row.side,
            interval_volume=row.interval_volume,
            open_interest=row.open_interest,
            vol_oi=row.vol_oi,
            otm_percent=row.otm_percent,
            bid_percent=row.bid_percent,
            ask_percent=row.ask_percent,
            premium=row.premium,
            avg_fill=row.avg_fill,
            multileg_percent=row.multileg_percent,
        )
        for row in rows
    ]


# =============================================================================
# A 股股票基本信息工具
# =============================================================================


@mcp.tool(annotations={"readOnlyHint": True})
async def cn_stock_get_basic_info(
    symbol: Annotated[
        str,
        Field(
            description="股票代码（6位数字，如 '600519', '000001'）",
            min_length=1,
        ),
    ],
) -> StockBasicInfoResult:
    """获取 A 股股票基本信息。

    包含股票名称、当前价格、总市值、所属行业、上市日期等基本信息。
    适用于基本面分析的初始查询，快速了解公司概况。

    数据源：东方财富
    """
    normalized_symbol = symbol.strip()

    def parse_float(val: Any) -> float | None:
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def infer_a_share_market_prefix(code: str) -> str:
        if code.startswith("6"):
            return "sh"
        if code.startswith(("0", "2", "3")):
            return "sz"
        return "sh"

    async def call_with_retry(func, *args, retries: int = 2, **kwargs):
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return await asyncio.to_thread(func, *args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt >= retries:
                    break
                await asyncio.sleep(0.6 * (attempt + 1))
        assert last_exc is not None
        raise last_exc

    try:
        # 优先使用东方财富接口（字段最全）
        try:
            em_df = await call_with_retry(
                ak.stock_individual_info_em,
                symbol=normalized_symbol,
                retries=2,
            )
            if not em_df.empty:
                data = dict(zip(em_df["item"], em_df["value"], strict=True))
                price = parse_float(data.get("最新价"))
                if price is not None:
                    return StockBasicInfoResult(
                        symbol=normalized_symbol,
                        info=StockBasicInfoItem(
                            symbol=normalized_symbol,
                            name=str(data.get("股票简称", "")),
                            price=price,
                            market_cap=parse_float(data.get("总市值")),
                            industry=str(data.get("行业", "")),
                            listing_date=str(data.get("上市时间", "")),
                        ),
                    )
        except Exception as em_exc:
            logger.warning(
                "stock_individual_info_em failed, fallback to cninfo+sina symbol=%s error=%s",
                normalized_symbol,
                em_exc,
            )

        # 回退方案：cninfo(静态信息) + 新浪行情（优先日线，失败再分钟线）
        profile_error: Exception | None = None
        profile_df = None
        profile_row = None
        try:
            profile_df = await call_with_retry(
                ak.stock_profile_cninfo,
                symbol=normalized_symbol,
                retries=1,
            )
            if profile_df is not None and not profile_df.empty:
                profile_row = profile_df.iloc[0]
        except Exception as profile_exc:
            profile_error = profile_exc
            logger.warning(
                "stock_profile_cninfo failed symbol=%s error=%s",
                normalized_symbol,
                profile_exc,
            )

        prefixed_symbol = f"{infer_a_share_market_prefix(normalized_symbol)}{normalized_symbol}"

        price: float | None = None
        market_cap: float | None = None
        daily_error: Exception | None = None
        try:
            daily_df = await call_with_retry(
                ak.stock_zh_a_daily,
                symbol=prefixed_symbol,
                adjust="",
                retries=1,
            )
            if daily_df is not None and not daily_df.empty:
                latest = daily_df.iloc[-1]
                price = parse_float(latest.get("close"))
                outstanding_share = parse_float(latest.get("outstanding_share"))
                market_cap = price * outstanding_share if price is not None and outstanding_share is not None else None
        except Exception as daily_exc:
            daily_error = daily_exc
            logger.warning(
                "stock_zh_a_daily failed symbol=%s error=%s",
                prefixed_symbol,
                daily_exc,
            )

        if price is None:
            try:
                minute_df = await call_with_retry(
                    ak.stock_zh_a_minute,
                    symbol=prefixed_symbol,
                    period="5",
                    retries=1,
                )
                if minute_df is not None and not minute_df.empty:
                    latest_minute = minute_df.iloc[-1]
                    price = parse_float(latest_minute.get("close"))
            except Exception as minute_exc:
                logger.warning(
                    "stock_zh_a_minute failed symbol=%s error=%s",
                    prefixed_symbol,
                    minute_exc,
                )

        if price is None:
            detail = []
            if profile_error is not None:
                detail.append(f"profile={profile_error}")
            if daily_error is not None:
                detail.append(f"daily={daily_error}")
            error_text = "; ".join(detail) if detail else "无可用行情数据"
            raise ToolError(f"股票 {normalized_symbol} 获取最新价失败: {error_text}")

        display_name = ""
        industry = None
        listing_date = None
        if profile_row is not None:
            display_name = str(profile_row.get("A股简称") or profile_row.get("公司名称") or "")
            industry = str(profile_row.get("所属行业") or "")
            listing_date = str(profile_row.get("上市日期") or "")

        return StockBasicInfoResult(
            symbol=normalized_symbol,
            info=StockBasicInfoItem(
                symbol=normalized_symbol,
                name=display_name,
                price=price,
                market_cap=market_cap,
                industry=industry,
                listing_date=listing_date,
            ),
        )

    except Exception as exc:
        logger.error("获取股票基本信息失败 symbol=%s error=%s", normalized_symbol, exc)
        raise ToolError(f"获取股票 {normalized_symbol} 基本信息失败: {str(exc)}") from exc


@mcp.tool(annotations={"readOnlyHint": True})
async def cn_stock_get_financial_statements(
    symbol: Annotated[str, Field(description="股票代码")],
    period: Annotated[
        Literal["report", "yearly"],
        Field(description="周期类型 (report=按报告期, yearly=按年度)"),
    ] = "report",
) -> FinancialStatementsResult:
    """获取 A 股财务报表数据 (资产负债/利润/现金流)。

    默认返回最近 8 期数据。包含营业收入、净利润、总资产、负债、现金流等核心字段。
    """
    normalized_symbol = symbol.strip()

    def to_em_symbol(code: str) -> str:
        code_upper = code.upper()
        if "." in code_upper:
            return code_upper
        if len(code_upper) == 6 and code_upper.isdigit():
            if code_upper.startswith("6"):
                return f"{code_upper}.SH"
            if code_upper.startswith(("0", "2", "3")):
                return f"{code_upper}.SZ"
            if code_upper.startswith(("4", "8")):
                return f"{code_upper}.BJ"
        return code_upper

    try:
        em_symbol = to_em_symbol(normalized_symbol)

        # 定义需要并发获取的任务
        tasks = []
        if period == "report":
            tasks = [
                asyncio.to_thread(
                    ak.stock_profit_sheet_by_report_em,
                    symbol=em_symbol,
                ),
                asyncio.to_thread(
                    ak.stock_balance_sheet_by_report_em,
                    symbol=em_symbol,
                ),
                asyncio.to_thread(
                    ak.stock_cash_flow_sheet_by_report_em,
                    symbol=em_symbol,
                ),
            ]
        else:
            tasks = [
                asyncio.to_thread(
                    ak.stock_profit_sheet_by_yearly_em,
                    symbol=em_symbol,
                ),
                asyncio.to_thread(
                    ak.stock_balance_sheet_by_yearly_em,
                    symbol=em_symbol,
                ),
                asyncio.to_thread(
                    ak.stock_cash_flow_sheet_by_yearly_em,
                    symbol=em_symbol,
                ),
            ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常并合并数据
        dfs = []
        for res in results:
            if isinstance(res, Exception):
                logger.error(f"获取报表失败: {res}")
                dfs.append(pd.DataFrame())
            else:
                dfs.append(res)

        df_profit, df_balance, df_cash = dfs[0], dfs[1], dfs[2]

        # 统一列名 REPORT_DATE 并转为 datetime 以便合并
        # akshare 返回的列名通常是中文，REPORT_DATE 可能是 "REPORT_DATE" 或 "报告期"
        # 东方财富接口通常返回大写英文列名或者中文列名，需检查
        # 假设 akshare 已经标准化，或者我们需要通过打印 columns 确认
        # 这里假设列名包含 "REPORT_DATE" 或 "报告期"

        def standardize_date_col(df: pd.DataFrame) -> pd.DataFrame:
            if df.empty:
                return df
            col_map = {c: "REPORT_DATE" for c in df.columns if c in ["REPORT_DATE", "报告期", "PUBLISH_DATE"]}
            df = df.rename(columns=col_map)
            # 有些接口可能没有 REPORT_DATE，只有日期列
            return df

        df_profit = standardize_date_col(df_profit)
        df_balance = standardize_date_col(df_balance)
        df_cash = standardize_date_col(df_cash)

        # 能够合并的前提是有共同的 REPORT_DATE
        # 如果 df 为空则跳过
        merged = pd.DataFrame()
        if not df_profit.empty:
            merged = df_profit

        if not df_balance.empty:
            if merged.empty:
                merged = df_balance
            else:
                merged = pd.merge(
                    merged,
                    df_balance,
                    on="REPORT_DATE",
                    how="outer",
                    suffixes=("", "_bal"),
                )

        if not df_cash.empty:
            if merged.empty:
                merged = df_cash
            else:
                merged = pd.merge(
                    merged,
                    df_cash,
                    on="REPORT_DATE",
                    how="outer",
                    suffixes=("", "_cash"),
                )

        if merged.empty:
            return FinancialStatementsResult(
                symbol=normalized_symbol,
                period=period,
                count=0,
                statements=[],
            )

        # 按日期降序，取最近 8 期
        if "REPORT_DATE" in merged.columns:
            merged["REPORT_DATE"] = pd.to_datetime(merged["REPORT_DATE"], errors="coerce")
            merged = merged.sort_values("REPORT_DATE", ascending=False).head(8)
        else:
            merged = merged.head(8)

        # 辅助函数：安全获取 float
        def get_val(row, keys: list[str]) -> float | None:
            for k in keys:
                if k in row and pd.notna(row[k]):
                    try:
                        return float(row[k])
                    except (TypeError, ValueError):
                        pass
            return None

        statements = []
        for _, row in merged.iterrows():
            report_date = row.get("REPORT_DATE")
            if pd.isna(report_date):
                continue

            item = FinancialStatementItem(
                report_date=report_date.strftime("%Y-%m-%d"),
                # 利润表
                revenue=get_val(
                    row,
                    [
                        "TOTAL_OPERATE_INCOME",
                        "营业总收入",
                        "OPERATE_INCOME",
                        "营业收入",
                    ],
                ),
                net_profit=get_val(row, ["PARENT_NETPROFIT", "归母净利润", "NETPROFIT", "净利润"]),
                net_profit_deduct_non_recurring=get_val(row, ["DEDUCT_PARENT_NETPROFIT", "扣非净利润"]),
                # 资产负债表
                total_assets=get_val(row, ["TOTAL_ASSETS", "资产总计"]),
                total_liabilities=get_val(row, ["TOTAL_LIABILITIES", "负债合计"]),
                total_equity=get_val(row, ["TOTAL_EQUITY", "股东权益合计", "SHEQUITY", "所有者权益合计"]),
                # 现金流量表
                operating_cash_flow=get_val(row, ["NETCASH_OPERATE", "经营活动产生的现金流量净额"]),
                investing_cash_flow=get_val(row, ["NETCASH_INVEST", "投资活动产生的现金流量净额"]),
                financing_cash_flow=get_val(row, ["NETCASH_FINANCE", "筹资活动产生的现金流量净额"]),
            )
            statements.append(item)

        return FinancialStatementsResult(
            symbol=normalized_symbol,
            period=period,
            count=len(statements),
            statements=statements,
        )

    except Exception as exc:
        logger.error("获取财务报表失败 symbol=%s error=%s", normalized_symbol, exc)
        raise ToolError(f"获取股票 {normalized_symbol} 财务报表失败: {str(exc)}") from exc


@mcp.tool(annotations={"readOnlyHint": True})
async def cn_stock_get_financial_metrics(
    symbol: Annotated[str, Field(description="股票代码")],
) -> FinancialMetricsResult:
    """获取 A 股关键财务指标 (ROE/PE/EPS 等)。

    数据源：东方财富-财务指标分析
    """
    normalized_symbol = symbol.strip()

    def to_em_symbol(code: str) -> str:
        code_upper = code.upper()
        if "." in code_upper:
            return code_upper
        if len(code_upper) == 6 and code_upper.isdigit():
            if code_upper.startswith("6"):
                return f"{code_upper}.SH"
            if code_upper.startswith(("0", "2", "3")):
                return f"{code_upper}.SZ"
            if code_upper.startswith(("4", "8")):
                return f"{code_upper}.BJ"
        return code_upper

    def get_val(row: pd.Series, keys: list[str]) -> float | None:
        for key in keys:
            if key in row and pd.notna(row[key]):
                try:
                    return float(row[key])
                except (ValueError, TypeError):
                    continue
        return None

    def infer_a_share_market_prefix(code: str) -> str:
        if code.startswith("6"):
            return "sh"
        if code.startswith(("0", "2", "3")):
            return "sz"
        return "sh"

    async def fetch_latest_price(code: str) -> float | None:
        prefixed_symbol = f"{infer_a_share_market_prefix(code)}{code}"
        try:
            daily_df = await asyncio.to_thread(
                ak.stock_zh_a_daily,
                symbol=prefixed_symbol,
                adjust="",
            )
            if not daily_df.empty:
                close_val = pd.to_numeric(daily_df.iloc[-1].get("close"), errors="coerce")
                if pd.notna(close_val):
                    return float(close_val)
        except Exception as daily_exc:
            logger.warning(
                "stock_zh_a_daily failed in financial_metrics symbol=%s error=%s",
                prefixed_symbol,
                daily_exc,
            )

        try:
            minute_df = await asyncio.to_thread(
                ak.stock_zh_a_minute,
                symbol=prefixed_symbol,
                period="5",
            )
            if not minute_df.empty:
                close_val = pd.to_numeric(minute_df.iloc[-1].get("close"), errors="coerce")
                if pd.notna(close_val):
                    return float(close_val)
        except Exception as minute_exc:
            logger.warning(
                "stock_zh_a_minute failed in financial_metrics symbol=%s error=%s",
                prefixed_symbol,
                minute_exc,
            )

        return None

    try:
        em_symbol = to_em_symbol(normalized_symbol)

        try:
            # 东方财富接口要求 symbol 带市场后缀，例如 600519.SH
            df = await asyncio.to_thread(
                ak.stock_financial_analysis_indicator_em,
                symbol=em_symbol,
            )
        except Exception as em_exc:
            logger.warning(
                "stock_financial_analysis_indicator_em failed symbol=%s error=%s",
                em_symbol,
                em_exc,
            )
            # 回退新浪接口，避免单一数据源失败导致整体不可用
            df = await asyncio.to_thread(
                ak.stock_financial_analysis_indicator,
                symbol=normalized_symbol,
            )

        if not isinstance(df, pd.DataFrame) or df.empty:
            return FinancialMetricsResult(symbol=normalized_symbol, count=0, metrics=[])

        date_col = None
        for candidate in ("REPORT_DATE", "日期", "report_date"):
            if candidate in df.columns:
                date_col = candidate
                break

        if date_col is not None:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            df = df.sort_values(date_col, ascending=False)

        latest_row: pd.Series | None = None
        latest_date_text = ""
        for _, row in df.iterrows():
            date_text = ""
            if date_col is not None:
                date_val = row.get(date_col)
                if pd.notna(date_val):
                    date_text = date_val.strftime("%Y-%m-%d") if hasattr(date_val, "strftime") else str(date_val)

            if not date_text:
                for alt in ("REPORT_DATE_NAME", "报告期", "日期"):
                    if alt in row and pd.notna(row[alt]):
                        date_text = str(row[alt])
                        break

            if date_text:
                latest_row = row
                latest_date_text = date_text
                break

        if latest_row is None:
            return FinancialMetricsResult(symbol=normalized_symbol, count=0, metrics=[])

        eps_val = get_val(latest_row, ["EPSJB", "BASIC_EPS", "每股收益(元)", "每股收益"])
        bvps_val = get_val(latest_row, ["BPS", "每股净资产(元)", "每股净资产"])
        latest_price = await fetch_latest_price(normalized_symbol)

        pe_val = None
        if latest_price is not None and eps_val is not None and eps_val > 0:
            pe_val = latest_price / eps_val

        pb_val = None
        if latest_price is not None and bvps_val is not None and bvps_val > 0:
            pb_val = latest_price / bvps_val

        latest_metric = FinancialMetricItem(
            report_date=latest_date_text,
            eps=eps_val,
            bvps=bvps_val,
            pe=pe_val,
            pb=pb_val,
            roe=get_val(latest_row, ["ROEJQ", "净资产收益率(%)", "ROE"]),
            gross_margin=get_val(
                latest_row,
                ["XSMLL", "销售毛利率(%)", "GROSS_PROFIT_RATIO"],
            ),
            net_margin=get_val(
                latest_row,
                ["XSJLL", "销售净利率(%)", "NET_PROFIT_RATIO"],
            ),
            debt_to_asset_ratio=get_val(
                latest_row,
                ["ZCFZL", "资产负债率(%)", "DEBT_ASSET_RATIO"],
            ),
        )

        return FinancialMetricsResult(
            symbol=normalized_symbol,
            count=1,
            metrics=[latest_metric],
        )

    except Exception as exc:
        logger.error("获取财务指标失败 symbol=%s error=%s", normalized_symbol, exc)
        raise ToolError(f"获取股票 {normalized_symbol} 财务指标失败: {str(exc)}") from exc


@mcp.tool(annotations={"readOnlyHint": True})
async def hk_stock_get_financial_statements(
    stock: Annotated[str, Field(description="港股代码，如 '00700'")],
    period: Annotated[
        Literal["report", "yearly"],
        Field(description="周期类型 (report=按报告期, yearly=按年度)"),
    ] = "report",
) -> FinancialStatementsResult:
    """获取港股财务报表数据 (资产负债/利润/现金流)。"""
    normalized_stock = normalize_hk_stock_code(stock)

    def to_wide(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame()
        if not {"REPORT_DATE", "STD_ITEM_NAME", "AMOUNT"}.issubset(df.columns):
            return pd.DataFrame()

        temp = df[["REPORT_DATE", "STD_ITEM_NAME", "AMOUNT"]].copy()
        temp["REPORT_DATE"] = pd.to_datetime(temp["REPORT_DATE"], errors="coerce")
        temp = temp[pd.notna(temp["REPORT_DATE"]) & pd.notna(temp["STD_ITEM_NAME"])]
        if temp.empty:
            return pd.DataFrame()

        temp["AMOUNT"] = pd.to_numeric(temp["AMOUNT"], errors="coerce")
        wide = (
            temp.pivot_table(
                index="REPORT_DATE",
                columns="STD_ITEM_NAME",
                values="AMOUNT",
                aggfunc="first",
            )
            .reset_index()
            .sort_values("REPORT_DATE", ascending=False)
        )
        return wide

    def get_val(row: pd.Series, keys: list[str]) -> float | None:
        for key in keys:
            if key in row and pd.notna(row[key]):
                try:
                    return float(row[key])
                except (ValueError, TypeError):
                    continue
        return None

    try:
        # 港股接口 ak.stock_financial_hk_report_em(stock="00700", symbol="资产负债表", indicator="年度")
        indicator = "年度" if period == "yearly" else "报告期"

        tasks = [
            asyncio.to_thread(
                ak.stock_financial_hk_report_em,
                stock=normalized_stock,
                symbol="利润表",
                indicator=indicator,
            ),
            asyncio.to_thread(
                ak.stock_financial_hk_report_em,
                stock=normalized_stock,
                symbol="资产负债表",
                indicator=indicator,
            ),
            asyncio.to_thread(
                ak.stock_financial_hk_report_em,
                stock=normalized_stock,
                symbol="现金流量表",
                indicator=indicator,
            ),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        dfs: list[pd.DataFrame] = []
        for name, res in zip(["利润表", "资产负债表", "现金流量表"], results, strict=True):
            if isinstance(res, Exception):
                logger.error("获取港股%s失败 stock=%s error=%s", name, normalized_stock, res)
                dfs.append(pd.DataFrame())
            else:
                dfs.append(to_wide(res))

        df_profit, df_balance, df_cash = dfs

        merged = pd.DataFrame()
        if not df_profit.empty:
            merged = df_profit

        if not df_balance.empty:
            if merged.empty:
                merged = df_balance
            else:
                merged = pd.merge(
                    merged,
                    df_balance,
                    on="REPORT_DATE",
                    how="outer",
                    suffixes=("", "_bal"),
                )

        if not df_cash.empty:
            if merged.empty:
                merged = df_cash
            else:
                merged = pd.merge(
                    merged,
                    df_cash,
                    on="REPORT_DATE",
                    how="outer",
                    suffixes=("", "_cash"),
                )

        if merged.empty:
            return FinancialStatementsResult(
                symbol=normalized_stock,
                period=period,
                count=0,
                statements=[],
            )

        if "REPORT_DATE" in merged.columns:
            merged["REPORT_DATE"] = pd.to_datetime(merged["REPORT_DATE"], errors="coerce")
            merged = merged.sort_values("REPORT_DATE", ascending=False).head(8)
        else:
            merged = merged.head(8)

        statements = []
        for _, row in merged.iterrows():
            report_date = row.get("REPORT_DATE")
            if pd.isna(report_date):
                continue

            item = FinancialStatementItem(
                report_date=report_date.strftime("%Y-%m-%d"),
                # 利润表
                revenue=get_val(
                    row,
                    ["营业额", "营业收入", "营运收入", "净利息收入", "其他经营收入"],
                ),
                net_profit=get_val(
                    row,
                    [
                        "股东应占溢利",
                        "股东应占利润",
                        "归属股东利益",
                        "净利润",
                        "持续经营业务税后利润",
                    ],
                ),
                # 港股有些接口可能没有扣非
                # 资产负债表
                total_assets=get_val(row, ["总资产", "资产总计"]),
                total_liabilities=get_val(row, ["总负债", "负债总计"]),
                total_equity=get_val(row, ["总权益", "股东权益", "股东权益合计"]),
                # 现金流量表
                operating_cash_flow=get_val(
                    row,
                    [
                        "经营业务现金净额",
                        "经营活动现金流量净额",
                        "经营活动产生的现金流量净额",
                    ],
                ),
                investing_cash_flow=get_val(
                    row,
                    [
                        "投资业务现金净额",
                        "投资活动现金流量净额",
                        "投资活动产生的现金流量净额",
                    ],
                ),
                financing_cash_flow=get_val(
                    row,
                    [
                        "融资业务现金净额",
                        "融资活动现金流量净额",
                        "筹资活动现金流量净额",
                    ],
                ),
            )
            statements.append(item)

        return FinancialStatementsResult(
            symbol=normalized_stock,
            period=period,
            count=len(statements),
            statements=statements,
        )

    except Exception as exc:
        logger.error("获取港股报表失败 stock=%s error=%s", normalized_stock, exc)
        raise ToolError(f"获取港股 {normalized_stock} 财务报表失败: {str(exc)}") from exc


@mcp.tool(annotations={"readOnlyHint": True})
async def hk_stock_get_financial_metrics(
    stock: Annotated[str, Field(description="港股代码，如 '00700'")],
) -> FinancialMetricsResult:
    """获取港股关键财务指标 (ROE/PE/EPS 等)。"""
    normalized_stock = normalize_hk_stock_code(stock)

    def get_val(row: pd.Series, keys: list[str]) -> float | None:
        for key in keys:
            if key in row and pd.notna(row[key]):
                try:
                    return float(str(row[key]).replace(",", ""))
                except (ValueError, TypeError):
                    continue
        return None

    try:
        # 港股主要财务指标（按报告期）
        df = await asyncio.to_thread(
            ak.stock_financial_hk_analysis_indicator_em,
            symbol=normalized_stock,
            indicator="报告期",
        )

        if not isinstance(df, pd.DataFrame) or df.empty:
            return FinancialMetricsResult(symbol=normalized_stock, count=0, metrics=[])

        if "REPORT_DATE" in df.columns:
            df["REPORT_DATE"] = pd.to_datetime(df["REPORT_DATE"], errors="coerce")
            df = df.sort_values("REPORT_DATE", ascending=False)

        latest_row = None
        latest_date = None
        for _, row in df.iterrows():
            date_val = row.get("REPORT_DATE")
            if pd.notna(date_val):
                latest_row = row
                latest_date = date_val
                break

        if latest_row is None or latest_date is None:
            return FinancialMetricsResult(symbol=normalized_stock, count=0, metrics=[])

        # 取一份最新核心指标补齐 PE/PB
        pe_val = None
        pb_val = None
        try:
            core_df = await asyncio.to_thread(
                ak.stock_hk_financial_indicator_em,
                symbol=normalized_stock,
            )
            if not core_df.empty:
                core_row = core_df.iloc[0]
                pe_val = get_val(core_row, ["市盈率", "PE_TTM"])
                pb_val = get_val(core_row, ["市净率", "PB_TTM"])
        except Exception as core_exc:
            logger.warning(
                "stock_hk_financial_indicator_em failed stock=%s error=%s",
                normalized_stock,
                core_exc,
            )

        latest_metric = FinancialMetricItem(
            report_date=latest_date.strftime("%Y-%m-%d"),
            eps=get_val(latest_row, ["BASIC_EPS", "基本每股收益"]),
            bvps=get_val(latest_row, ["BPS", "每股净资产"]),
            pe=pe_val,
            pb=pb_val,
            roe=get_val(latest_row, ["ROE_AVG", "净资产收益率"]),
            gross_margin=get_val(latest_row, ["GROSS_PROFIT_RATIO", "销售毛利率"]),
            net_margin=get_val(latest_row, ["NET_PROFIT_RATIO", "销售净利率"]),
            debt_to_asset_ratio=get_val(latest_row, ["DEBT_ASSET_RATIO", "资产负债率"]),
        )

        return FinancialMetricsResult(
            symbol=normalized_stock,
            count=1,
            metrics=[latest_metric],
        )

    except Exception as exc:
        logger.error("获取港股指标失败 stock=%s error=%s", normalized_stock, exc)
        raise ToolError(f"获取港股 {normalized_stock} 财务指标失败: {str(exc)}") from exc


@mcp.tool(annotations={"readOnlyHint": True})
async def get_china_macro_indicators(
    category: Annotated[
        Literal[
            "overview",
            "growth",
            "inflation",
            "pmi",
            "monetary",
            "financing",
            "trade",
            "real_estate",
            "employment",
            "consumption",
            "industrial",
            "fdi",
        ],
        Field(
            description=(
                "数据类别: overview(总览), growth(增长), inflation(通胀), pmi(PMI), "
                "monetary(货币), financing(社融), trade(贸易), real_estate(房地产), "
                "employment(就业), consumption(消费), industrial(工业), fdi(外资)"
            )
        ),
    ] = "overview",
    days: Annotated[
        int | None,
        Field(
            description="可选：最近N天数据。留空时不做时间过滤，返回各指标最新可用值",
            ge=1,
            le=36500,
        ),
    ] = None,
    start_date: Annotated[
        str | None,
        Field(description="可选起始日期 (YYYY-MM-DD)。提供后将忽略 days"),
    ] = None,
    end_date: Annotated[
        str | None,
        Field(description="可选结束日期 (YYYY-MM-DD)。留空则不限制结束日期"),
    ] = None,
) -> MacroIndicatorsResult:
    """获取中国宏观经济数据。"""
    try:
        start, end = resolve_optional_date_range(days, start_date, end_date)

        async def fetch(
            _indicator_id: str,
            indicator_name_cn: str,
            func,
            *args,
            unit: str | None = None,
            value_candidates: tuple[str, ...] = (),
            date_candidates: tuple[str, ...] = (),
            item_filter: tuple[str, str] | None = None,
            **kwargs,
        ):
            try:
                df = await asyncio.to_thread(func, *args, **kwargs)
                if df.empty:
                    return None, f"{indicator_name_cn}: 数据为空"

                latest, col_date, col_val = _normalize_macro_latest(
                    df,
                    start=start,
                    end=end,
                    date_candidates=date_candidates,
                    value_candidates=value_candidates,
                    item_filter=item_filter,
                )

                value = pd.to_numeric(latest[col_val], errors="coerce")
                if pd.isna(value):
                    return None, f"{indicator_name_cn}: {col_val} 为空"

                parsed_date = latest.get("_parsed_date")
                date_text = ""
                if col_date and col_date in latest and pd.notna(latest[col_date]):
                    date_text = _format_date_text(latest[col_date])
                elif pd.notna(parsed_date):
                    date_text = parsed_date.strftime("%Y-%m-%d")

                return (
                    MacroIndicatorItem(
                        name=indicator_name_cn,
                        value=float(value),
                        unit=unit,
                        date=date_text,
                    ),
                    None,
                )
            except Exception as e:
                return None, f"{indicator_name_cn}: {e}"

        tasks = []

        if category in ["overview", "growth"]:
            tasks.append(
                fetch(
                    "cn_gdp_yoy",
                    "GDP季度",
                    ak.macro_china_gdp,
                    unit="%",
                    value_candidates=("国内生产总值-同比增长",),
                    date_candidates=("季度",),
                )
            )

        if category in ["overview", "inflation"]:
            tasks.append(
                fetch(
                    "cn_cpi_yoy",
                    "CPI月度",
                    ak.macro_china_cpi,
                    unit="%",
                    value_candidates=("全国-同比增长",),
                    date_candidates=("月份",),
                )
            )
            tasks.append(
                fetch(
                    "cn_ppi_yoy",
                    "PPI年率",
                    ak.macro_china_ppi_yearly,
                    unit="%",
                    value_candidates=("今值",),
                    date_candidates=("日期",),
                )
            )

        if category in ["overview", "pmi"]:
            tasks.append(
                fetch(
                    "cn_official_manufacturing_pmi",
                    "官方制造业PMI",
                    ak.macro_china_pmi,
                    unit="点",
                    value_candidates=("制造业-指数",),
                    date_candidates=("月份",),
                )
            )
            tasks.append(
                fetch(
                    "cn_caixin_manufacturing_pmi",
                    "财新制造业PMI",
                    ak.macro_china_cx_pmi_yearly,
                    unit="点",
                    value_candidates=("今值",),
                    date_candidates=("日期",),
                )
            )

        if category in ["overview", "monetary"]:
            tasks.append(
                fetch(
                    "cn_m2_yoy",
                    "M2货币供应年率",
                    ak.macro_china_money_supply,
                    unit="%",
                    value_candidates=("货币和准货币(M2)-同比增长",),
                    date_candidates=("月份",),
                )
            )
            tasks.append(
                fetch(
                    "cn_lpr_1y",
                    "LPR_1Y",
                    ak.macro_china_lpr,
                    unit="%",
                    value_candidates=("LPR1Y",),
                    date_candidates=("TRADE_DATE",),
                )
            )

        if category in ["overview", "financing"]:
            tasks.append(
                fetch(
                    "cn_social_financing_increment",
                    "社融规模增量",
                    ak.macro_china_shrzgm,
                    unit="亿元",
                    value_candidates=("社会融资规模增量",),
                    date_candidates=("月份",),
                )
            )

        if category in ["overview", "trade"]:
            tasks.append(
                fetch(
                    "cn_trade_balance",
                    "贸易差额",
                    ak.macro_china_trade_balance,
                    unit="亿美元",
                    value_candidates=("今值",),
                    date_candidates=("日期",),
                )
            )
            tasks.append(
                fetch(
                    "cn_fx_reserves",
                    "外汇储备",
                    ak.macro_china_fx_reserves_yearly,
                    unit="亿美元",
                    value_candidates=("今值",),
                    date_candidates=("日期",),
                )
            )

        if category in ["overview", "real_estate"]:
            tasks.append(
                fetch(
                    "cn_new_house_price_yoy",
                    "70城新建住宅价格指数",
                    ak.macro_china_new_house_price,
                    unit="点",
                    value_candidates=("新建商品住宅价格指数-同比",),
                    date_candidates=("日期",),
                )
            )

        if category in ["overview", "employment"]:
            tasks.append(
                fetch(
                    "cn_urban_unemployment_rate",
                    "城镇调查失业率",
                    ak.macro_china_urban_unemployment,
                    unit="%",
                    value_candidates=("value",),
                    date_candidates=("date",),
                    item_filter=("item", "全国城镇调查失业率"),
                )
            )

        if category in ["overview", "consumption"]:
            tasks.append(
                fetch(
                    "cn_retail_sales_yoy",
                    "社会消费品零售总额",
                    ak.macro_china_consumer_goods_retail,
                    unit="%",
                    value_candidates=("同比增长",),
                    date_candidates=("月份",),
                )
            )

        if category in ["overview", "industrial"]:
            tasks.append(
                fetch(
                    "cn_industrial_production_yoy",
                    "规模以上工业增加值年率",
                    ak.macro_china_industrial_production_yoy,
                    unit="%",
                    value_candidates=("今值",),
                    date_candidates=("日期",),
                )
            )

        if category in ["overview", "fdi"]:
            tasks.append(
                fetch(
                    "cn_fdi_yoy",
                    "实际使用外资FDI",
                    ak.macro_china_fdi,
                    unit="%",
                    value_candidates=("累计-同比增长", "当月-同比增长"),
                    date_candidates=("月份",),
                )
            )

        results = await asyncio.gather(*tasks)
        indicators = [item for item, _ in results if item]
        failures = [err for item, err in results if not item and err]

        if failures:
            logger.warning("中国宏观指标抓取部分失败: %s", "; ".join(failures[:8]))
        if not indicators:
            raise ToolError("获取中国宏观数据失败: 无可用指标，请检查 AKShare 接口变更或上游数据源。")

        return MacroIndicatorsResult(
            category=category,
            count=len(indicators),
            indicators=indicators,
        )

    except Exception as exc:
        logger.error(f"获取中国宏观数据失败: {exc}")
        raise ToolError(f"获取中国宏观数据失败: {str(exc)}") from exc


@mcp.tool(annotations={"readOnlyHint": True})
async def get_hk_macro_indicators(
    days: Annotated[
        int | None,
        Field(
            description="可选：最近N天数据。留空时不做时间过滤，返回各指标最新可用值",
            ge=1,
            le=36500,
        ),
    ] = None,
    start_date: Annotated[
        str | None,
        Field(description="可选起始日期 (YYYY-MM-DD)。提供后将忽略 days"),
    ] = None,
    end_date: Annotated[
        str | None,
        Field(description="可选结束日期 (YYYY-MM-DD)。留空则不限制结束日期"),
    ] = None,
) -> MacroIndicatorsResult:
    """获取香港宏观经济数据 (GDP/CPI/失业率)。"""
    try:
        start, end = resolve_optional_date_range(days, start_date, end_date)

        async def fetch(
            _indicator_id: str,
            indicator_name_cn: str,
            func,
            *,
            unit: str | None = None,
            value_candidates: tuple[str, ...] = (),
            date_candidates: tuple[str, ...] = (),
        ):
            try:
                df = await asyncio.to_thread(func)
                if df.empty:
                    return None, f"{indicator_name_cn}: 数据为空"

                latest, col_date, col_val = _normalize_macro_latest(
                    df,
                    start=start,
                    end=end,
                    date_candidates=date_candidates,
                    value_candidates=value_candidates,
                )

                value = pd.to_numeric(latest[col_val], errors="coerce")
                if pd.isna(value):
                    return None, f"{indicator_name_cn}: {col_val} 为空"

                parsed_date = latest.get("_parsed_date")
                date_text = ""
                if col_date and col_date in latest and pd.notna(latest[col_date]):
                    date_text = _format_date_text(latest[col_date])
                elif pd.notna(parsed_date):
                    date_text = parsed_date.strftime("%Y-%m-%d")

                return (
                    MacroIndicatorItem(
                        name=indicator_name_cn,
                        value=float(value),
                        unit=unit,
                        date=date_text,
                    ),
                    None,
                )
            except Exception as e:
                return None, f"{indicator_name_cn}: {e}"

        tasks = [
            fetch(
                "hk_gdp",
                "香港GDP",
                ak.macro_china_hk_gbp,
                unit="百万港元",
                value_candidates=("现值",),
                date_candidates=("时间", "发布日期"),
            ),
            fetch(
                "hk_cpi",
                "香港CPI",
                ak.macro_china_hk_cpi,
                unit="点",
                value_candidates=("现值",),
                date_candidates=("时间", "发布日期"),
            ),
            fetch(
                "hk_unemployment_rate",
                "香港失业率",
                ak.macro_china_hk_rate_of_unemployment,
                unit="%",
                value_candidates=("现值",),
                date_candidates=("时间", "发布日期"),
            ),
        ]
        results = await asyncio.gather(*tasks)
        indicators = [item for item, _ in results if item]
        failures = [err for item, err in results if not item and err]

        if failures:
            logger.warning("香港宏观指标抓取部分失败: %s", "; ".join(failures[:8]))
        if not indicators:
            raise ToolError("获取香港宏观数据失败: 无可用指标，请检查 AKShare 接口变更或上游数据源。")

        return MacroIndicatorsResult(
            category="HK",
            count=len(indicators),
            indicators=indicators,
        )
    except Exception as exc:
        logger.error(f"获取香港宏观数据失败: {exc}")
        raise ToolError(f"获取香港宏观数据失败: {str(exc)}") from exc


@mcp.tool(annotations={"readOnlyHint": True})
async def get_us_macro_indicators(
    category: Annotated[
        Literal["overview", "growth", "inflation", "employment", "business"],
        Field(
            description=("数据类别: overview(总览), growth(增长), inflation(通胀), employment(就业), business(景气)")
        ),
    ] = "overview",
    days: Annotated[
        int | None,
        Field(
            description="可选：最近N天数据。留空时不做时间过滤，返回各指标最新可用值",
            ge=1,
            le=36500,
        ),
    ] = None,
    start_date: Annotated[
        str | None,
        Field(description="可选起始日期 (YYYY-MM-DD)。提供后将忽略 days"),
    ] = None,
    end_date: Annotated[
        str | None,
        Field(description="可选结束日期 (YYYY-MM-DD)。留空则不限制结束日期"),
    ] = None,
) -> MacroIndicatorsResult:
    """获取美国宏观经济数据。"""
    try:
        start, end = resolve_optional_date_range(days, start_date, end_date)

        async def fetch(
            _indicator_id: str,
            indicator_name_cn: str,
            func,
            *args,
            unit: str | None = None,
            value_candidates: tuple[str, ...] = (),
            date_candidates: tuple[str, ...] = (),
        ):
            try:
                df = await asyncio.to_thread(func, *args)
                if df.empty:
                    return None, f"{indicator_name_cn}: 数据为空"

                latest, col_date, col_val = _normalize_macro_latest(
                    df,
                    start=start,
                    end=end,
                    date_candidates=date_candidates,
                    value_candidates=value_candidates,
                )

                value = pd.to_numeric(latest[col_val], errors="coerce")
                if pd.isna(value):
                    return None, f"{indicator_name_cn}: {col_val} 为空"

                parsed_date = latest.get("_parsed_date")
                date_text = ""
                if col_date and col_date in latest and pd.notna(latest[col_date]):
                    date_text = _format_date_text(latest[col_date])
                elif pd.notna(parsed_date):
                    date_text = parsed_date.strftime("%Y-%m-%d")

                return (
                    MacroIndicatorItem(
                        name=indicator_name_cn,
                        value=float(value),
                        unit=unit,
                        date=date_text,
                    ),
                    None,
                )
            except Exception as e:
                return None, f"{indicator_name_cn}: {e}"

        tasks = []
        if category in ["overview", "growth"]:
            tasks.append(
                fetch(
                    "us_gdp",
                    "美国GDP",
                    ak.macro_usa_gdp_monthly,
                    unit="%",
                    value_candidates=("今值",),
                    date_candidates=("日期",),
                )
            )  # 只有月度/季度接口需确认，假设 akshare 有 macro_usa_gdp

        if category in ["overview", "inflation"]:
            tasks.append(
                fetch(
                    "us_cpi",
                    "美国CPI",
                    ak.macro_usa_cpi_yoy,
                    unit="%",
                    value_candidates=("今值",),
                    date_candidates=("日期",),
                )
            )
            tasks.append(
                fetch(
                    "us_ppi",
                    "美国PPI",
                    ak.macro_usa_ppi,
                    unit="%",
                    value_candidates=("今值",),
                    date_candidates=("日期",),
                )
            )

        if category in ["overview", "employment"]:
            tasks.append(
                fetch(
                    "us_non_farm_payrolls",
                    "非农就业人口",
                    ak.macro_usa_non_farm,
                    unit="千人",
                    value_candidates=("今值",),
                    date_candidates=("日期",),
                )
            )
            tasks.append(
                fetch(
                    "us_unemployment_rate",
                    "失业率",
                    ak.macro_usa_unemployment_rate,
                    unit="%",
                    value_candidates=("今值",),
                    date_candidates=("日期",),
                )
            )

        if category in ["overview", "business"]:
            tasks.append(
                fetch(
                    "us_ism_manufacturing_pmi",
                    "ISM制造业PMI",
                    ak.macro_usa_ism_pmi,
                    unit="点",
                    value_candidates=("今值",),
                    date_candidates=("日期",),
                )
            )

        results = await asyncio.gather(*tasks)
        indicators = [item for item, _ in results if item]
        failures = [err for item, err in results if not item and err]

        if failures:
            logger.warning("美国宏观指标抓取部分失败: %s", "; ".join(failures[:8]))
        if not indicators:
            raise ToolError("获取美国宏观数据失败: 无可用指标，请检查 AKShare 接口变更或上游数据源。")

        return MacroIndicatorsResult(
            category=category,
            count=len(indicators),
            indicators=indicators,
        )
    except Exception as exc:
        logger.error(f"获取美国宏观数据失败: {exc}")
        raise ToolError(f"获取美国宏观数据失败: {str(exc)}") from exc


@mcp.tool(annotations={"readOnlyHint": True})
async def get_economic_calendar(
    days: Annotated[int, Field(description="查询未来多少天的数据", ge=1, le=30)] = 7,
    start_date: Annotated[str | None, Field(description="起始日期 (YYYY-MM-DD)，与days二选一")] = None,
    end_date: Annotated[str | None, Field(description="结束日期 (YYYY-MM-DD)，与days二选一")] = None,
) -> EconomicCalendarResult:
    """查询财经日历，获取经济指标、央行决议等全球财经事件。

    数据源：百度股市通。支持查询当天和未来的财经事件。
    """
    try:
        start, end = resolve_date_range(days, start_date, end_date)
        date_range = [start + timedelta(days=i) for i in range((end - start).days + 1)]

        tasks = [asyncio.to_thread(ak.news_economic_baidu, date=d.strftime("%Y%m%d")) for d in date_range]
        dfs = await asyncio.gather(*tasks, return_exceptions=True)

        events = []
        for d, df in zip(date_range, dfs, strict=True):
            if isinstance(df, Exception):
                logger.warning(f"获取 {d} 的财经日历数据失败: {df}")
                continue
            if df.empty:
                continue

            for _, row in df.iterrows():
                events.append(
                    EconomicCalendarItem(
                        date=str(row.get("日期", d.strftime("%Y-%m-%d"))),
                        time=str(row.get("时间", "")),
                        country=str(row.get("地区", "")),
                        event=str(row.get("事件", "")),
                        actual=str(row["公布"]) if pd.notna(row.get("公布")) else None,
                        forecast=str(row["预期"]) if pd.notna(row.get("预期")) else None,
                        previous=str(row["前值"]) if pd.notna(row.get("前值")) else None,
                        importance=int(row.get("重要性", 1)),
                    )
                )

        return EconomicCalendarResult(
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            count=len(events),
            events=events,
        )
    except Exception as exc:
        logger.error(f"获取财经日历失败: {exc}")
        raise ToolError(f"获取财经日历失败: {str(exc)}") from exc


@mcp.tool(annotations={"readOnlyHint": True})
async def get_earnings_calendar(
    days: Annotated[int, Field(description="查询未来多少天的数据", ge=1, le=30)] = 7,
    start_date: Annotated[str | None, Field(description="起始日期 (YYYY-MM-DD)，与days二选一")] = None,
    end_date: Annotated[str | None, Field(description="结束日期 (YYYY-MM-DD)，与days二选一")] = None,
    exchange: Annotated[str | None, Field(description="交易所过滤: US(美股)/HK(港股)/SH(沪股)/SZ(深股)")] = None,
) -> EarningsCalendarResult:
    """查询财报日历，获取美股、港股、A股的财报发布日期。

    数据源：百度股市通。支持查询当天和未来的财报发布计划。
    """
    try:
        start, end = resolve_date_range(days, start_date, end_date)
        date_range = [start + timedelta(days=i) for i in range((end - start).days + 1)]

        tasks = [asyncio.to_thread(ak.news_report_time_baidu, date=d.strftime("%Y%m%d")) for d in date_range]
        dfs = await asyncio.gather(*tasks, return_exceptions=True)

        earnings = []
        for d, df in zip(date_range, dfs, strict=True):
            if isinstance(df, Exception):
                logger.warning(f"获取 {d} 的财报日历数据失败: {df}")
                continue
            if df.empty:
                continue

            for _, row in df.iterrows():
                row_exchange = str(row.get("交易所", "")).upper()

                # 交易所过滤
                if exchange and row_exchange != exchange.upper():
                    continue

                earnings.append(
                    EarningsCalendarItem(
                        symbol=str(row.get("股票代码", "")),
                        name=str(row.get("股票简称", "")),
                        exchange=row_exchange,
                        report_type=str(row.get("财报类型", "")),
                        release_time=str(row.get("发布时间", "--")),
                        market_cap=int(row["市值"]) if pd.notna(row.get("市值")) else None,
                        report_date=str(row.get("发布日期", d.strftime("%Y-%m-%d"))),
                    )
                )

        return EarningsCalendarResult(
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            count=len(earnings),
            earnings=earnings,
        )
    except Exception as exc:
        logger.error(f"获取财报日历失败: {exc}")
        raise ToolError(f"获取财报日历失败: {str(exc)}") from exc
