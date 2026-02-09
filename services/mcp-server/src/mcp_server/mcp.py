import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any, Literal

import httpx
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
    FlowSummaryResult,
    MacroFactorSnapshotItem,
    MacroFactorSnapshotsResult,
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
