import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastmcp import FastMCP
from shared.database import session_scope

from shared.models.news import NewsArticle
from shared.models.options import OptionsFlow
from shared.models.stocks import StockPrice
from sqlalchemy import func, select

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

mcp = FastMCP("Finance", json_response=True)


def get_stock_api_url() -> str:
    return os.getenv("STOCK_API_URL", "http://stock-api:3000")


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


@mcp.tool()
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


@mcp.tool()
async def get_latest_stock_price(symbol: str, timeframe: str = "1") -> str:
    normalized_symbol = symbol.strip().upper()
    normalized_timeframe = timeframe.strip() or "1"

    stmt = (
        select(StockPrice)
        .where(StockPrice.symbol == normalized_symbol)
        .where(StockPrice.timeframe == normalized_timeframe)
        .order_by(StockPrice.timestamp.desc())
        .limit(1)
    )

    async with session_scope() as session:
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()

    if row is None:
        return json.dumps(
            {
                "symbol": normalized_symbol,
                "timeframe": normalized_timeframe,
                "row": None,
            },
            indent=2,
        )

    return json.dumps(
        {
            "symbol": normalized_symbol,
            "timeframe": normalized_timeframe,
            "row": {
                "timestamp": row.timestamp.isoformat(),
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
            },
        },
        indent=2,
    )


@mcp.tool()
async def query_news_articles(
    days: int = 7,
    symbols: list[str] | None = None,
    type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> str:
    if limit <= 0:
        return json.dumps({"error": "limit must be > 0"}, indent=2)
    if offset < 0:
        return json.dumps({"error": "offset must be >= 0"}, indent=2)

    since = datetime.now(tz=timezone.utc) - timedelta(days=days)

    stmt = select(NewsArticle).where(NewsArticle.published_at >= since)

    if type:
        stmt = stmt.where(NewsArticle.type == type)

    if symbols:
        normalized_symbols = [
            s.strip().upper() for s in symbols if isinstance(s, str) and s.strip()
        ]
        if normalized_symbols:
            stmt = stmt.where(NewsArticle.symbols.overlap(normalized_symbols))

    stmt = stmt.order_by(NewsArticle.published_at.desc()).offset(offset).limit(limit)

    async with session_scope() as session:
        result = await session.execute(stmt)
        rows = result.scalars().all()

    payload = {
        "since": since.isoformat(),
        "limit": limit,
        "offset": offset,
        "count": len(rows),
        "articles": [
            {
                "external_id": row.external_id,
                "type": row.type,
                "title": row.title,
                "url": row.url,
                "author": row.author,
                "symbols": row.symbols,
                "tags": row.tags,
                "importance": row.importance,
                "published_at": row.published_at.isoformat(),
            }
            for row in rows
        ],
    }

    return json.dumps(payload, indent=2)


async def fetch_stock_api_json(path: str, params: dict[str, str]) -> dict[str, Any]:
    url = get_stock_api_url().rstrip("/") + path
    timeout = httpx.Timeout(30.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()
        if isinstance(payload, dict):
            return payload
        raise ValueError("stock-api response is not a JSON object")


@mcp.tool()
async def fetch_stock_history(
    symbol: str,
    timeframe: str = "D",
    range: int = 200,
    to: int | None = None,
) -> str:
    params: dict[str, str] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "range": str(range),
    }
    if to is not None:
        params["to"] = str(to)

    try:
        payload = await fetch_stock_api_json("/history", params)
        return json.dumps(payload, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, indent=2)


@mcp.tool()
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


@mcp.tool()
async def fetch_technical_analysis(symbol: str) -> str:
    try:
        payload = await fetch_stock_api_json("/ta", {"symbol": symbol})
        return json.dumps(payload, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, indent=2)


@mcp.tool()
async def list_private_indicators() -> str:
    try:
        payload = await fetch_stock_api_json("/indicators/private", {})
        return json.dumps(payload, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, indent=2)


@mcp.tool()
async def query_options_flow(
    symbol: str | None = None,
    side: str | None = None,
    option_type: str | None = None,
    days: int = 7,
    min_premium: float | None = None,
    limit: int = 50,
) -> str:
    """
    查询期权大单数据。

    Args:
        symbol: 股票代码 (如 "BSX", "AAPL")
        side: 交易方向 ("Bid" 或 "Ask")
        option_type: 期权类型 ("P" 看跌, "C" 看涨)
        days: 查询最近N天的数据
        min_premium: 最小权利金过滤
        limit: 返回结果数量限制

    Returns:
        JSON格式的期权大单数据列表
    """
    since = datetime.now() - timedelta(days=days)

    stmt = select(OptionsFlow).where(OptionsFlow.timestamp >= since)

    if symbol:
        stmt = stmt.where(OptionsFlow.symbol == symbol.upper())
    if side:
        stmt = stmt.where(OptionsFlow.side == side.capitalize())
    if option_type:
        stmt = stmt.where(OptionsFlow.option_type == option_type.upper())
    if min_premium:
        stmt = stmt.where(OptionsFlow.premium >= min_premium)

    stmt = stmt.order_by(OptionsFlow.timestamp.desc()).limit(limit)

    async with session_scope() as session:
        result = await session.execute(stmt)
        rows = result.scalars().all()

    results = [
        {
            "timestamp": row.timestamp.isoformat(),
            "symbol": row.symbol,
            "strike": row.strike,
            "option_type": row.option_type,
            "expiry": row.expiry.isoformat(),
            "dte": row.dte,
            "side": row.side,
            "interval_volume": row.interval_volume,
            "open_interest": row.open_interest,
            "vol_oi": row.vol_oi,
            "otm_percent": row.otm_percent,
            "bid_percent": row.bid_percent,
            "ask_percent": row.ask_percent,
            "premium": row.premium,
            "avg_fill": row.avg_fill,
            "multileg_percent": row.multileg_percent,
        }
        for row in rows
    ]
    return json.dumps(results, indent=2)


@mcp.tool()
async def get_flow_summary(days: int = 1) -> str:
    """
    获取期权流向汇总统计。

    Args:
        days: 统计最近N天的数据

    Returns:
        JSON格式的汇总统计，包括:
        - 总交易数
        - 按方向统计 (Bid vs Ask)
        - 按类型统计 (Put vs Call)
        - Top 10 活跃标的
        - 总权利金
    """
    since = datetime.now() - timedelta(days=days)

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

    summary = {
        "period_days": days,
        "total_trades": total.count or 0,
        "total_premium": total.total_premium or 0,
        "by_side": {
            row.side: {"count": row.count, "premium": row.premium} for row in by_side
        },
        "by_type": {
            row.option_type: {"count": row.count, "premium": row.premium}
            for row in by_type
        },
        "top_symbols": [
            {"symbol": row.symbol, "count": row.count, "premium": row.total_premium}
            for row in top_symbols
        ],
    }

    return json.dumps(summary, indent=2, default=str)


@mcp.tool()
async def get_unusual_activity(
    days: int = 1,
    min_vol_oi: float = 5.0,
    limit: int = 20,
) -> str:
    """
    获取异常期权活动 (高 Vol/OI 比率)。

    Args:
        days: 查询最近N天
        min_vol_oi: 最小成交量/未平仓量比率
        limit: 返回结果数量

    Returns:
        JSON格式的异常活动列表，按 Vol/OI 降序排列
    """
    since = datetime.now() - timedelta(days=days)

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

    results = [
        {
            "timestamp": row.timestamp.isoformat(),
            "symbol": row.symbol,
            "strike": row.strike,
            "option_type": row.option_type,
            "expiry": row.expiry.isoformat(),
            "side": row.side,
            "interval_volume": row.interval_volume,
            "open_interest": row.open_interest,
            "vol_oi": row.vol_oi,
            "premium": row.premium,
            "avg_fill": row.avg_fill,
        }
        for row in rows
    ]
    return json.dumps(results, indent=2)


def main():
    logger.info("Starting MCP server")
    mcp.run()


if __name__ == "__main__":
    main()
