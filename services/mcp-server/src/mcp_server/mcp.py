import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field, ValidationError
from shared.database import session_scope
from shared.logging import configure_logging
from shared.models.news import NewsArticle
from shared.models.options import OptionsFlow
from shared.models.stocks import StockPrice
from sqlalchemy import func, select

from .schemas import (
    FlowSummaryResult,
    NewsArticleItem,
    NewsArticlesResult,
    OptionsFlowItem,
    OptionsSide,
    OptionType,
    SideStats,
    StockHistoryResult,
    Timeframe,
    TopSymbol,
    TypeStats,
)

configure_logging(service="mcp-server")
logger = logging.getLogger(__name__)

mcp = FastMCP("Finance")


def get_stock_api_url() -> str:
    return os.getenv("FA_MCP_SERVER_STOCK_API_URL", "http://stock-api:3000")


def safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


def parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


# @mcp.tool()
async def query_stock_prices(
    symbol: str,
    timeframe: str = "1",
    days: int | None = 7,
    start: str | None = None,
    end: str | None = None,
    limit: int = 500,
    order: str = "asc",
) -> str:
    if limit <= 0:
        return json.dumps({"error": "limit must be > 0"}, indent=2)

    normalized_symbol = symbol.strip().upper()
    normalized_timeframe = timeframe.strip() or "1"

    if start and days is not None:
        return json.dumps({"error": "use either start/end or days, not both"}, indent=2)

    if start:
        since = parse_iso_datetime(start)
        until = parse_iso_datetime(end) if end else datetime.now(tz=timezone.utc)
    else:
        since_days = days if days is not None else 7
        since = datetime.now(tz=timezone.utc) - timedelta(days=since_days)
        until = datetime.now(tz=timezone.utc)

    stmt = (
        select(StockPrice)
        .where(StockPrice.symbol == normalized_symbol)
        .where(StockPrice.timeframe == normalized_timeframe)
        .where(StockPrice.timestamp >= since)
        .where(StockPrice.timestamp <= until)
    )

    stmt = stmt.order_by(
        StockPrice.timestamp.desc()
        if order.lower() == "desc"
        else StockPrice.timestamp.asc()
    ).limit(limit)

    async with session_scope() as session:
        result = await session.execute(stmt)
        rows = result.scalars().all()

    payload = {
        "symbol": normalized_symbol,
        "timeframe": normalized_timeframe,
        "start": since.isoformat(),
        "end": until.isoformat(),
        "order": order,
        "count": len(rows),
        "rows": [
            {
                "timestamp": row.timestamp.isoformat(),
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
            }
            for row in rows
        ],
    }

    return json.dumps(payload, indent=2)


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
        Field(description="股票代码列表，如 ['AAPL', 'TSLA']。留空则不过滤"),
    ] = None,
    type: Annotated[
        str | None,
        Field(description="新闻类型过滤。留空则返回所有类型"),
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


async def fetch_stock_api_json(path: str, params: dict[str, str]) -> dict[str, Any]:
    url = get_stock_api_url().rstrip("/") + path
    timeout = httpx.Timeout(30.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def fetch_stock_history(
    symbol: Annotated[
        str,
        Field(
            description="股票代码，如 'AAPL', 'TSLA' (无需交易所前缀)",
            min_length=1,
        ),
    ],
    timeframe: Annotated[
        Timeframe,
        Field(
            description=(
                "时间周期: '1','3','5','15','30','45','60','120','180','240','D','W','M'"
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
    返回结果按时间升序排列 (最早的在前)。
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
    except httpx.HTTPStatusError as exc:
        raise ToolError(
            f"获取股票历史数据失败 (HTTP {exc.response.status_code}): {exc}"
        )
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
        Field(description="股票代码，如 'BSX', 'AAPL'。留空则返回所有标的"),
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
