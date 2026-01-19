import json
import logging
from datetime import datetime, timedelta

from fastmcp import FastMCP
from shared.database import session_scope

# Shared imports
from shared.models.options import OptionsFlow
from sqlalchemy import func, select

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

mcp = FastMCP("Options Flow", json_response=True)


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
