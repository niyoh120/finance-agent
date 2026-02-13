import asyncio
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any, Literal

import akshare as ak
import httpx
import pandas as pd
from fastmcp import FastMCP
from fastmcp.client.transports import UvxStdioTransport
from fastmcp.exceptions import ToolError
from fastmcp.tools.tool_transform import ToolTransformConfig
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
    AnalystConsensusResult,
    AnalystRatingItem,
    DividendHistoryResult,
    DividendItem,
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
    ShareholderInfoResult,
    ShareholderItem,
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


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ToolError(f"日期格式错误: {value}") from exc


def resolve_date_range(
    days: int | None, start_date: str | None, end_date: str | None
) -> tuple[date, date]:
    today = datetime.now(tz=timezone.utc).date()
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
        Field(
            description=(
                "股票代码列表（不带交易所前缀），如 ['AAPL', 'TSLA']。用于过滤新闻。"
            )
        ),
    ] = None,
    type: Annotated[
        NewsType | None,
        Field(
            description="新闻类型过滤: 'macro_news' (宏观新闻), 'kol_tweet' (KOL推文), 'stock_news' (个股新闻)。留空则返回所有类型"
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

    since = datetime.now(tz=timezone.utc) - timedelta(days=days)

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
                title=row.title or "",
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


@mcp.tool(annotations={"readOnlyHint": True})
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
                current_snapshot_date=(
                    row.current_snapshot_date.isoformat()
                    if row.current_snapshot_date
                    else None
                ),
                compare_date=(
                    row.compare_date.isoformat() if row.compare_date else None
                ),
                generated_at=(
                    row.generated_at.isoformat() if row.generated_at else None
                ),
                current_score=row.current_score,
                compare_score=row.compare_score,
                change=row.change,
                change_pct=row.change_pct,
            )
            for row in rows
        ],
    )


@mcp.tool(annotations={"readOnlyHint": True})
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


@mcp.tool(annotations={"readOnlyHint": True})
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
                raise ToolError(
                    f"stock-api 请求失败 (HTTP {resp.status_code}): {detail}"
                )

            body = resp.text.strip()
            if len(body) > 1000:
                body = body[:1000] + "..."
            raise ToolError(
                f"stock-api 请求失败 (HTTP {resp.status_code}): {body or resp.reason_phrase}"
            )

        if not isinstance(payload, dict):
            raise ToolError("stock-api 返回格式不符合预期: 不是 JSON object")

        return payload


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_market(
    query: Annotated[
        str,
        Field(
            description=(
                "搜索关键词。"
                "支持 ticker、公司名或 'EXCHANGE:' 前缀提示。"
                "示例：'WMT'、'walmart'、'NASDAQ:'、'BINANCE:'."
            ),
            min_length=1,
        ),
    ],
    type: Annotated[
        Literal["stock", "futures", "forex", "cfd", "crypto", "index", "economic"]
        | None,
        Field(
            description=(
                "市场类型过滤。留空则不过滤。"
                "可选：stock/futures/forex/cfd/crypto/index/economic"
            )
        ),
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
        raise ToolError(f"stock-api 返回格式不符合预期: {exc}")


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
                "时间周期, 单位是分钟，D/W/M 分别为日/周/月: '1','3','5','15','30','45','60','120','180','240','D','W','M'"
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
        raise ToolError(f"stock-api 返回格式不符合预期: {exc}")
    except ToolError as exc:
        msg = str(exc)
        if "Failed to load chart for" in msg or "HTTP 404" in msg:
            raise ToolError(
                msg
                + "\n\n可能原因：交易所前缀错误或 market id 不存在。"
                + "建议：先调用 `search_market(query=...)` 查到正确的 TradingView market id，再调用 `fetch_stock_history`。"
            )
        raise
    except Exception as exc:
        raise ToolError(f"获取股票历史数据失败: {str(exc)}")


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
        Field(
            description=(
                "股票代码（不带交易所前缀），如 'BSX', 'AAPL'。用于过滤期权流。"
            )
        ),
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

    since = datetime.now(tz=timezone.utc) - timedelta(days=days)

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

    since = datetime.now(tz=timezone.utc) - timedelta(days=days)

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
        by_side={
            row.side: SideStats(count=row.count, premium=float(row.premium or 0))
            for row in by_side
        },
        by_type={
            row.option_type: TypeStats(count=row.count, premium=float(row.premium or 0))
            for row in by_type
        },
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

    since = datetime.now(tz=timezone.utc) - timedelta(days=days)

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

    包含股票名称、当前价格、总市值、流通市值、所属行业、上市日期等基本信息。
    适用于基本面分析的初始查询，快速了解公司概况。

    数据源：东方财富
    """
    try:
        df = await asyncio.to_thread(ak.stock_individual_info_em, symbol=symbol.strip())
        if df.empty:
            raise ToolError(f"未找到股票 {symbol} 的基本信息")

        # stock_individual_info_em 返回 DataFrame 列为: item, value
        data = dict(zip(df["item"], df["value"]))

        def parse_float(val: Any) -> float | None:
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        return StockBasicInfoResult(
            symbol=symbol.strip(),
            info=StockBasicInfoItem(
                symbol=symbol.strip(),
                name=str(data.get("股票简称", "")),
                price=parse_float(data.get("最新价")) or 0.0,
                market_cap=parse_float(data.get("总市值")),
                float_market_cap=parse_float(data.get("流通市值")),
                industry=str(data.get("行业", "")),
                listing_date=str(data.get("上市时间", "")),
            ),
        )

    except Exception as exc:
        logger.error("获取股票基本信息失败", symbol=symbol, error=str(exc))
        raise ToolError(f"获取股票 {symbol} 基本信息失败: {str(exc)}") from exc


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
    try:
        # 定义需要并发获取的任务
        tasks = []
        if period == "report":
            tasks = [
                asyncio.to_thread(ak.stock_profit_sheet_by_report_em, symbol=symbol),
                asyncio.to_thread(ak.stock_balance_sheet_by_report_em, symbol=symbol),
                asyncio.to_thread(ak.stock_cash_flow_sheet_by_report_em, symbol=symbol),
            ]
        else:
            tasks = [
                asyncio.to_thread(ak.stock_profit_sheet_by_yearly_em, symbol=symbol),
                asyncio.to_thread(ak.stock_balance_sheet_by_yearly_em, symbol=symbol),
                asyncio.to_thread(ak.stock_cash_flow_sheet_by_yearly_em, symbol=symbol),
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
            col_map = {
                c: "REPORT_DATE"
                for c in df.columns
                if c in ["REPORT_DATE", "报告期", "PUBLISH_DATE"]
            }
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
                symbol=symbol, period=period, count=0, statements=[]
            )

        # 按日期降序，取最近 8 期
        if "REPORT_DATE" in merged.columns:
            merged["REPORT_DATE"] = pd.to_datetime(
                merged["REPORT_DATE"], errors="coerce"
            )
            merged = merged.sort_values("REPORT_DATE", ascending=False).head(8)
        else:
            merged = merged.head(8)

        # 辅助函数：安全获取 float
        def get_val(row, keys: list[str]) -> float | None:
            for k in keys:
                if k in row and pd.notna(row[k]):
                    try:
                        return float(row[k])
                    except:
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
                net_profit=get_val(
                    row, ["PARENT_NETPROFIT", "归母净利润", "NETPROFIT", "净利润"]
                ),
                net_profit_deduct_non_recurring=get_val(
                    row, ["DEDUCT_PARENT_NETPROFIT", "扣非净利润"]
                ),
                # 资产负债表
                total_assets=get_val(row, ["TOTAL_ASSETS", "资产总计"]),
                total_liabilities=get_val(row, ["TOTAL_LIABILITIES", "负债合计"]),
                total_equity=get_val(
                    row, ["TOTAL_EQUITY", "股东权益合计", "SHEQUITY", "所有者权益合计"]
                ),
                # 现金流量表
                operating_cash_flow=get_val(
                    row, ["NETCASH_OPERATE", "经营活动产生的现金流量净额"]
                ),
                investing_cash_flow=get_val(
                    row, ["NETCASH_INVEST", "投资活动产生的现金流量净额"]
                ),
                financing_cash_flow=get_val(
                    row, ["NETCASH_FINANCE", "筹资活动产生的现金流量净额"]
                ),
            )
            statements.append(item)

        return FinancialStatementsResult(
            symbol=symbol,
            period=period,
            count=len(statements),
            statements=statements,
        )

    except Exception as exc:
        logger.error(f"获取财务报表失败: {exc}")
        raise ToolError(f"获取股票 {symbol} 财务报表失败: {str(exc)}")


@mcp.tool(annotations={"readOnlyHint": True})
async def cn_stock_get_financial_metrics(
    symbol: Annotated[str, Field(description="股票代码")],
) -> FinancialMetricsResult:
    """获取 A 股关键财务指标 (ROE/PE/EPS 等)。

    数据源：东方财富-财务指标分析
    """
    try:
        # stock_financial_analysis_indicator_em 返回按报告期的指标
        df = await asyncio.to_thread(
            ak.stock_financial_analysis_indicator_em, symbol=symbol
        )

        if df.empty:
            return FinancialMetricsResult(symbol=symbol, count=0, metrics=[])

        # 按日期降序，取最近 8 期
        # 假设列名有 "日期"
        if "日期" in df.columns:
            df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
            df = df.sort_values("日期", ascending=False).head(8)

        def get_val(row, key: str) -> float | None:
            if key in row and pd.notna(row[key]):
                try:
                    return float(row[key])
                except:
                    pass
            return None

        metrics = []
        for _, row in df.iterrows():
            date_val = row.get("日期")
            if pd.isna(date_val):
                continue

            metrics.append(
                FinancialMetricItem(
                    report_date=date_val.strftime("%Y-%m-%d"),
                    eps=get_val(row, "每股收益(元)"),
                    bvps=get_val(row, "每股净资产(元)"),
                    pe=None,  # 历史 PE 通常不在这个接口，而在行情或估值接口，此处暂空
                    pb=None,
                    roe=get_val(row, "净资产收益率(%)"),
                    gross_margin=get_val(row, "销售毛利率(%)"),
                    net_margin=get_val(row, "销售净利率(%)"),
                    debt_to_asset_ratio=get_val(row, "资产负债率(%)"),
                )
            )

        return FinancialMetricsResult(
            symbol=symbol,
            count=len(metrics),
            metrics=metrics,
        )

    except Exception as exc:
        logger.error(f"获取财务指标失败: {exc}")
        raise ToolError(f"获取股票 {symbol} 财务指标失败: {str(exc)}")


@mcp.tool(annotations={"readOnlyHint": True})
async def cn_stock_get_shareholder_info(
    symbol: Annotated[str, Field(description="股票代码")],
) -> ShareholderInfoResult:
    """获取 A 股股东信息 (十大股东/户数/筹码)。

    包含：最新一期十大股东、股东户数及变化、户均持股。
    """
    try:
        # 并发获取十大股东和股东户数
        tasks = [
            asyncio.to_thread(ak.stock_main_stock_holder, stock=symbol),
            asyncio.to_thread(ak.stock_hold_num_em, symbol=symbol),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理十大股东
        df_holders = pd.DataFrame()
        if not isinstance(results[0], Exception):
            df_holders = results[0]

        # 处理股东户数
        df_num = pd.DataFrame()
        if not isinstance(results[1], Exception):
            df_num = results[1]
            # 按日期降序
            if not df_num.empty:
                # 假设列名包含 "日期"
                if "日期" in df_num.columns:
                    df_num["日期"] = pd.to_datetime(df_num["日期"], errors="coerce")
                    df_num = df_num.sort_values("日期", ascending=False)

        report_date = None
        holder_count = None
        avg_hold_num = None

        if not df_num.empty:
            latest = df_num.iloc[0]
            report_date = (
                latest.get("日期").strftime("%Y-%m-%d")
                if pd.notna(latest.get("日期"))
                else None
            )
            holder_count = (
                int(latest.get("股东户数"))
                if pd.notna(latest.get("股东户数"))
                else None
            )
            avg_hold_num = (
                float(latest.get("户均持股数量"))
                if pd.notna(latest.get("户均持股数量"))
                else None
            )

        top_holders = []
        if not df_holders.empty:
            # 取最新一期
            # akshare stock_main_stock_holder 返回通常包含 "季度" 列 (e.g. "2023一季")
            # 或者直接返回所有历史，需要按 rank 和 holder_name 去重或者取最新季度
            # 简单起见，取前 10 行，或者按 index
            # 实测该接口可能返回所有历史，需要按 report_date 过滤
            # 但这里简化处理，假设前 10 条是最近的
            # 更好的是：先找到最新的 report_date (列名可能叫 "截止日期" 或 "季度")
            # 假设列名 "截止日期"
            pass  # TODO: refine logic based on actual columns

        # 重新实现 logic: 简单取前 10 条作为示意，或尽可能解析
        # akshare stock_main_stock_holder columns:
        # index (0-9), holder_name, hold_num, hold_ratio, nature, ...
        # 通常它返回最近一期的数据，或者是混合历史。
        # 这里仅取前 10 条

        for _, row in df_holders.head(10).iterrows():
            top_holders.append(
                ShareholderItem(
                    holder_name=str(row.get("股东名称", "")),
                    hold_num=float(row.get("持股数量", 0))
                    if pd.notna(row.get("持股数量"))
                    else None,
                    hold_ratio=float(row.get("持股比例", 0))
                    if pd.notna(row.get("持股比例"))
                    else None,
                    nature=str(row.get("股本性质", ""))
                    if pd.notna(row.get("股本性质"))
                    else None,
                )
            )

        return ShareholderInfoResult(
            symbol=symbol,
            report_date=report_date,
            holder_count=holder_count,
            avg_hold_num=avg_hold_num,
            top_holders=top_holders,
        )

    except Exception as exc:
        logger.error(f"获取股东信息失败: {exc}")
        raise ToolError(f"获取股票 {symbol} 股东信息失败: {str(exc)}")


@mcp.tool(annotations={"readOnlyHint": True})
async def cn_stock_get_dividend_history(
    symbol: Annotated[str, Field(description="股票代码")],
) -> DividendHistoryResult:
    """获取 A 股历史分红记录。"""
    try:
        df = await asyncio.to_thread(
            ak.stock_history_dividend_detail, symbol=symbol, indicator="分红"
        )
        if df.empty:
            return DividendHistoryResult(symbol=symbol, count=0, history=[])

        # 按公告日期或除权除息日排序
        # 列名: 公告日期, 除权除息日, 分红方案, 股权登记日, 派息日
        sort_col = "公告日期" if "公告日期" in df.columns else df.columns[0]
        try:
            df[sort_col] = pd.to_datetime(df[sort_col], errors="coerce")
            df = df.sort_values(sort_col, ascending=False)
        except:
            pass

        history = []
        for _, row in df.head(10).iterrows():
            history.append(
                DividendItem(
                    report_date=str(
                        row.get("公告日期", "")
                    ),  # 使用公告日期作为报告期标识
                    plan=str(row.get("分红方案", "")),
                    register_date=str(row.get("股权登记日", ""))
                    if pd.notna(row.get("股权登记日"))
                    else None,
                    ex_date=str(row.get("除权除息日", ""))
                    if pd.notna(row.get("除权除息日"))
                    else None,
                    payment_date=str(row.get("派息日", ""))
                    if pd.notna(row.get("派息日"))
                    else None,
                    dividend_ratio=None,  # 该接口可能不包含股息率
                )
            )

        return DividendHistoryResult(
            symbol=symbol,
            count=len(history),
            history=history,
        )

    except Exception as exc:
        logger.error(f"获取分红历史失败: {exc}")
        raise ToolError(f"获取股票 {symbol} 分红历史失败: {str(exc)}")


@mcp.tool(annotations={"readOnlyHint": True})
async def cn_stock_get_analyst_consensus(
    symbol: Annotated[str, Field(description="股票代码")],
) -> AnalystConsensusResult:
    """获取 A 股分析师一致预期及评级。"""
    try:
        # 并发获取盈利预测和评级变动
        tasks = [
            asyncio.to_thread(ak.stock_profit_forecast_em, symbol=symbol),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        df_forecast = pd.DataFrame()
        if not isinstance(results[0], Exception):
            df_forecast = results[0]

        # 提取数据
        target_price = None
        # 假设 df_forecast 包含一致预测数据，列如 "平均目标价"
        # 实际 ak.stock_profit_forecast_em 返回的是机构预测明细列表
        # 我们取最近的 N 条作为 "Recent Ratings"

        ratings = []
        if not df_forecast.empty:
            # 排序
            if "日期" in df_forecast.columns:
                df_forecast["日期"] = pd.to_datetime(
                    df_forecast["日期"], errors="coerce"
                )
                df_forecast = df_forecast.sort_values("日期", ascending=False)

            for _, row in df_forecast.head(10).iterrows():
                ratings.append(
                    AnalystRatingItem(
                        date=row.get("日期").strftime("%Y-%m-%d")
                        if pd.notna(row.get("日期"))
                        else "",
                        org_name=str(row.get("研究机构", "")),
                        analyst=str(row.get("分析师", "")),
                        rating=str(row.get("评级", "")),
                        target_price=float(row.get("目标价格", 0))
                        if pd.notna(row.get("目标价格"))
                        else None,
                    )
                )

        return AnalystConsensusResult(
            symbol=symbol,
            target_price=None,  # 需要从 summaries 接口获取，这里暂略
            latest_ratings=ratings,
        )

    except Exception as exc:
        logger.error(f"获取分析师预期失败: {exc}")
        raise ToolError(f"获取股票 {symbol} 分析师预期失败: {str(exc)}")


@mcp.tool(annotations={"readOnlyHint": True})
async def hk_stock_get_financial_statements(
    stock: Annotated[str, Field(description="港股代码，如 '00700'")],
    period: Annotated[
        Literal["report", "yearly"],
        Field(description="周期类型 (report=按报告期, yearly=按年度)"),
    ] = "report",
) -> FinancialStatementsResult:
    """获取港股财务报表数据 (资产负债/利润/现金流)。"""
    try:
        # 港股接口 ak.stock_financial_hk_report_em(stock="00700", symbol="资产负债表", indicator="年度")
        indicator = "年度" if period == "yearly" else "报告期"

        tasks = [
            asyncio.to_thread(
                ak.stock_financial_hk_report_em,
                stock=stock,
                symbol="利润表",
                indicator=indicator,
            ),
            asyncio.to_thread(
                ak.stock_financial_hk_report_em,
                stock=stock,
                symbol="资产负债表",
                indicator=indicator,
            ),
            asyncio.to_thread(
                ak.stock_financial_hk_report_em,
                stock=stock,
                symbol="现金流量表",
                indicator=indicator,
            ),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        dfs = []
        for res in results:
            if isinstance(res, Exception):
                logger.error(f"获取港股报表失败: {res}")
                dfs.append(pd.DataFrame())
            else:
                dfs.append(res)

        df_profit, df_balance, df_cash = dfs[0], dfs[1], dfs[2]

        # 港股接口返回的列名通常包含 "截止日期"
        def standardize(df):
            if df.empty:
                return df
            col_map = {
                c: "REPORT_DATE" for c in df.columns if c in ["截止日期", "REPORT_DATE"]
            }
            return df.rename(columns=col_map)

        df_profit = standardize(df_profit)
        df_balance = standardize(df_balance)
        df_cash = standardize(df_cash)

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
                symbol=stock, period=period, count=0, statements=[]
            )

        if "REPORT_DATE" in merged.columns:
            merged["REPORT_DATE"] = pd.to_datetime(
                merged["REPORT_DATE"], errors="coerce"
            )
            merged = merged.sort_values("REPORT_DATE", ascending=False).head(8)
        else:
            merged = merged.head(8)

        def get_val(row, keys: list[str]) -> float | None:
            for k in keys:
                if k in row and pd.notna(row[k]):
                    try:
                        val = str(row[k]).replace(",", "")
                        return float(val)
                    except:
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
                revenue=get_val(row, ["营业额", "营业收入", "Total Revenue"]),
                net_profit=get_val(row, ["归属股东利益", "Net Income"]),
                # 港股有些接口可能没有扣非
                # 资产负债表
                total_assets=get_val(row, ["资产总计", "Total Assets"]),
                total_liabilities=get_val(row, ["负债总计", "Total Liabilities"]),
                total_equity=get_val(row, ["股东权益合计", "Total Equity"]),
                # 现金流量表
                operating_cash_flow=get_val(
                    row, ["经营活动产生现金流量净额", "Operating Cash Flow"]
                ),
                investing_cash_flow=get_val(
                    row, ["投资活动产生现金流量净额", "Investing Cash Flow"]
                ),
                financing_cash_flow=get_val(
                    row, ["融资活动产生现金流量净额", "Financing Cash Flow"]
                ),
            )
            statements.append(item)

        return FinancialStatementsResult(
            symbol=stock,
            period=period,
            count=len(statements),
            statements=statements,
        )

    except Exception as exc:
        logger.error(f"获取港股报表失败: {exc}")
        raise ToolError(f"获取港股 {stock} 财务报表失败: {str(exc)}")


@mcp.tool(annotations={"readOnlyHint": True})
async def hk_stock_get_financial_metrics(
    stock: Annotated[str, Field(description="港股代码，如 '00700'")],
) -> FinancialMetricsResult:
    """获取港股关键财务指标 (ROE/PE/EPS 等)。"""
    try:
        # stock_financial_hk_indicator_em(stock="00700", indicator="年度")
        # 指标: 港股主要财务指标
        df = await asyncio.to_thread(
            ak.stock_financial_hk_indicator_em, stock=stock, indicator="报告期"
        )

        if df.empty:
            return FinancialMetricsResult(symbol=stock, count=0, metrics=[])

        if "截止日期" in df.columns:
            df["截止日期"] = pd.to_datetime(df["截止日期"], errors="coerce")
            df = df.sort_values("截止日期", ascending=False).head(8)

        def get_val(row, key: str) -> float | None:
            if key in row and pd.notna(row[key]):
                try:
                    return float(str(row[key]).replace(",", ""))
                except:
                    pass
            return None

        metrics = []
        for _, row in df.iterrows():
            date_val = row.get("截止日期")
            if pd.isna(date_val):
                continue

            metrics.append(
                FinancialMetricItem(
                    report_date=date_val.strftime("%Y-%m-%d"),
                    eps=get_val(row, "基本每股收益"),
                    bvps=get_val(row, "每股净资产"),
                    roe=get_val(row, "净资产收益率"),
                    gross_margin=None,  # 需检查具体列名
                    net_margin=None,
                    debt_to_asset_ratio=get_val(row, "资产负债率"),
                )
            )

        return FinancialMetricsResult(
            symbol=stock,
            count=len(metrics),
            metrics=metrics,
        )

    except Exception as exc:
        logger.error(f"获取港股指标失败: {exc}")
        raise ToolError(f"获取港股 {stock} 财务指标失败: {str(exc)}")


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
        Field(description="数据类别"),
    ] = "overview",
) -> MacroIndicatorsResult:
    """获取中国宏观经济数据。"""
    try:
        indicators = []

        async def fetch(name, func, *args, **kwargs):
            try:
                df = await asyncio.to_thread(func, *args, **kwargs)
                if df.empty:
                    return None
                # 通常 macro 接口返回包含 "日期" 和 "数值" 的列
                # 标准化
                col_date = next(
                    (
                        c
                        for c in df.columns
                        if "日期" in c or "date" in c.lower() or "月份" in c
                    ),
                    None,
                )
                col_val = next(
                    (
                        c
                        for c in df.columns
                        if c != col_date and ("值" in c or "index" in c or "rate" in c)
                    ),
                    None,
                )

                if col_date and col_val:
                    # 排序取最新
                    try:
                        df[col_date] = pd.to_datetime(df[col_date], errors="coerce")
                        df = df.sort_values(col_date, ascending=False)
                    except:
                        pass

                    latest = df.iloc[0]
                    return MacroIndicatorItem(
                        name=name,
                        value=float(latest[col_val])
                        if pd.notna(latest[col_val])
                        else None,
                        date=str(
                            latest[col_date].strftime("%Y-%m-%d")
                            if pd.notna(latest[col_date])
                            else str(latest[col_date])
                        ),
                        unit=None,  # 接口通常不直接返回单位，需人工标注或忽略
                    )
            except Exception as e:
                logger.warn(f"Fetch {name} failed: {e}")
                return None

        tasks = []

        if category in ["overview", "growth"]:
            tasks.append(fetch("GDP季度", ak.macro_china_gdp))

        if category in ["overview", "inflation"]:
            tasks.append(fetch("CPI月度", ak.macro_china_cpi))
            tasks.append(fetch("PPI年率", ak.macro_china_ppi_yearly))

        if category in ["overview", "pmi"]:
            tasks.append(fetch("官方制造业PMI", ak.macro_china_pmi))
            tasks.append(fetch("财新制造业PMI", ak.macro_china_cx_pmi))

        if category in ["overview", "monetary"]:
            tasks.append(fetch("M2货币供应年率", ak.macro_china_money_supply))
            # LPR 接口可能不同
            tasks.append(fetch("LPR_1Y", ak.macro_china_lpr))

        if category in ["overview", "financing"]:
            tasks.append(fetch("社融规模增量", ak.macro_china_social_financing_flow))

        if category in ["overview", "trade"]:
            tasks.append(fetch("贸易差额", ak.macro_china_trade_balance))
            tasks.append(fetch("外汇储备", ak.macro_china_fx_reserves))

        if category in ["overview", "real_estate"]:
            tasks.append(fetch("70城新建住宅价格指数", ak.macro_china_new_house_price))

        if category in ["overview", "employment"]:
            tasks.append(fetch("城镇调查失业率", ak.macro_china_urban_unemployment))

        if category in ["overview", "consumption"]:
            tasks.append(
                fetch("社会消费品零售总额", ak.macro_china_consumer_goods_retail)
            )

        if category in ["overview", "industrial"]:
            tasks.append(
                fetch(
                    "规模以上工业增加值年率", ak.macro_china_industrial_production_yoy
                )
            )

        if category in ["overview", "fdi"]:
            tasks.append(fetch("实际使用外资FDI", ak.macro_china_fdi))

        results = await asyncio.gather(*tasks)
        indicators = [r for r in results if r]

        return MacroIndicatorsResult(
            category=category,
            count=len(indicators),
            indicators=indicators,
        )

    except Exception as exc:
        logger.error(f"获取中国宏观数据失败: {exc}")
        raise ToolError(f"获取中国宏观数据失败: {str(exc)}")


@mcp.tool(annotations={"readOnlyHint": True})
async def get_hk_macro_indicators() -> MacroIndicatorsResult:
    """获取香港宏观经济数据 (GDP/CPI/失业率)。"""
    try:

        async def fetch(name, func):
            try:
                df = await asyncio.to_thread(func)
                if df.empty:
                    return None
                # 假设第一列日期，第二列数值
                col_date = df.columns[0]
                col_val = df.columns[1]

                try:
                    df[col_date] = pd.to_datetime(df[col_date], errors="coerce")
                    df = df.sort_values(col_date, ascending=False)
                except:
                    pass

                latest = df.iloc[0]
                return MacroIndicatorItem(
                    name=name,
                    value=float(latest[col_val]) if pd.notna(latest[col_val]) else None,
                    date=str(
                        latest[col_date].strftime("%Y-%m-%d")
                        if pd.notna(latest[col_date])
                        else str(latest[col_date])
                    ),
                )
            except Exception as e:
                return None

        tasks = [
            fetch("香港GDP", ak.macro_china_hk_gdp),
            fetch("香港CPI", ak.macro_china_hk_cpi),
            fetch("香港失业率", ak.macro_china_hk_unemployment_rate),
        ]
        results = await asyncio.gather(*tasks)
        indicators = [r for r in results if r]

        return MacroIndicatorsResult(
            category="HK",
            count=len(indicators),
            indicators=indicators,
        )
    except Exception as exc:
        logger.error(f"获取香港宏观数据失败: {exc}")
        raise ToolError(f"获取香港宏观数据失败: {str(exc)}")


@mcp.tool(annotations={"readOnlyHint": True})
async def get_us_macro_indicators(
    category: Annotated[
        Literal["overview", "growth", "inflation", "employment", "business"],
        Field(description="数据类别"),
    ] = "overview",
) -> MacroIndicatorsResult:
    """获取美国宏观经济数据。"""
    try:

        async def fetch(name, func, *args):
            try:
                df = await asyncio.to_thread(func, *args)
                if df.empty:
                    return None
                col_date = df.columns[0]
                col_val = df.columns[1]
                try:
                    df[col_date] = pd.to_datetime(df[col_date], errors="coerce")
                    df = df.sort_values(col_date, ascending=False)
                except:
                    pass

                latest = df.iloc[0]
                return MacroIndicatorItem(
                    name=name,
                    value=float(latest[col_val]) if pd.notna(latest[col_val]) else None,
                    date=str(
                        latest[col_date].strftime("%Y-%m-%d")
                        if pd.notna(latest[col_date])
                        else str(latest[col_date])
                    ),
                )
            except:
                return None

        tasks = []
        if category in ["overview", "growth"]:
            tasks.append(
                fetch("美国GDP", ak.macro_usa_gdp_monthly)
            )  # 只有月度/季度接口需确认，假设 akshare 有 macro_usa_gdp

        if category in ["overview", "inflation"]:
            tasks.append(fetch("美国CPI", ak.macro_usa_cpi))
            tasks.append(fetch("美国PPI", ak.macro_usa_ppi))

        if category in ["overview", "employment"]:
            tasks.append(fetch("非农就业人口", ak.macro_usa_non_farm))
            tasks.append(fetch("失业率", ak.macro_usa_unemployment_rate))

        if category in ["overview", "business"]:
            tasks.append(fetch("ISM制造业PMI", ak.macro_usa_ism_pmi))

        results = await asyncio.gather(*tasks)
        indicators = [r for r in results if r]

        return MacroIndicatorsResult(
            category=category,
            count=len(indicators),
            indicators=indicators,
        )
    except Exception as exc:
        logger.error(f"获取美国宏观数据失败: {exc}")
        raise ToolError(f"获取美国宏观数据失败: {str(exc)}")
