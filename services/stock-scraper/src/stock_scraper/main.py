import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

import aiohttp
import yaml
from shared.database import session_scope
from shared.logging import configure_logging
from shared.models.stocks import StockPrice
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

configure_logging(service="stock-scraper")
logger = logging.getLogger(__name__)


def get_stock_api_url() -> str:
    return os.getenv("FA_STOCK_SCRAPER_API_URL", "http://stock-api:3000")


def safe_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return default


def safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


async def fetch_history(
    session: aiohttp.ClientSession,
    symbol: str,
    timeframe: str,
    range_bars: int,
    to: int | None = None,
) -> list[dict[str, Any]]:
    url = get_stock_api_url()

    params: dict[str, str] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "range": str(range_bars),
    }
    if to is not None:
        params["to"] = str(to)

    try:
        async with session.get(f"{url}/history", params=params) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.warning(
                    "Failed to fetch history for %s: %s %s", symbol, resp.status, body
                )
                return []
            payload = await resp.json()
    except Exception as exc:
        logger.warning("Connection error to %s: %s", url, exc)
        return []

    candles = payload.get("candles")
    return candles if isinstance(candles, list) else []


async def get_latest_saved_timestamp(symbol: str, timeframe: str) -> datetime | None:
    async with session_scope() as session:
        stmt = select(func.max(StockPrice.timestamp)).where(
            StockPrice.symbol == symbol,
            StockPrice.timeframe == timeframe,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def upsert_candles(
    symbol: str, timeframe: str, candles: list[dict[str, Any]]
) -> int:
    rows: list[dict[str, Any]] = []

    for candle in candles:
        if not isinstance(candle, dict):
            continue

        time_s = safe_int(candle.get("time"))
        if time_s is None:
            continue

        ts = datetime.fromtimestamp(time_s, tz=timezone.utc)

        open_price = safe_float(candle.get("open"))
        high_price = safe_float(candle.get("high"))
        low_price = safe_float(candle.get("low"))
        close_price = safe_float(candle.get("close"))
        volume = safe_float(candle.get("volume"), 0.0)

        rows.append(
            {
                "symbol": symbol,
                "timestamp": ts,
                "timeframe": timeframe,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": volume,
            }
        )

    if not rows:
        return 0

    async with session_scope() as session:
        stmt = insert(StockPrice).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_stock_price",
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
            },
        )
        await session.execute(stmt)

    return len(rows)


async def sync_symbol(
    http_session: aiohttp.ClientSession,
    symbol: str,
    timeframe: str,
    range_bars: int,
    backfill_pages: int,
) -> None:
    normalized_symbol = symbol.strip().upper()

    last_ts = await get_latest_saved_timestamp(normalized_symbol, timeframe)
    last_sec = int(last_ts.timestamp()) if last_ts else None

    to: int | None = None
    oldest_seen: int | None = None

    pages = 0
    total_rows = 0

    while True:
        pages += 1
        candles = await fetch_history(
            http_session,
            symbol=normalized_symbol,
            timeframe=timeframe,
            range_bars=range_bars,
            to=to,
        )
        if not candles:
            break

        total_rows += await upsert_candles(normalized_symbol, timeframe, candles)

        times = [safe_int(c.get("time")) for c in candles if isinstance(c, dict)]
        times = [t for t in times if t is not None]
        if not times:
            break

        oldest = min(times)
        newest = max(times)

        if last_sec is not None:
            if last_sec > newest:
                break
            if oldest <= last_sec <= newest:
                break
        else:
            if pages >= backfill_pages:
                break

        if oldest_seen is not None and oldest >= oldest_seen:
            logger.warning(
                "History pagination stalled for %s (oldest=%s, prev_oldest=%s)",
                normalized_symbol,
                oldest,
                oldest_seen,
            )
            break

        oldest_seen = oldest
        to = oldest - 1

    logger.info(
        "Synced %s timeframe=%s pages=%s rows=%s last_saved=%s",
        normalized_symbol,
        timeframe,
        pages,
        total_rows,
        last_ts.isoformat() if last_ts else None,
    )


async def main() -> None:
    config_path = os.getenv("FA_STOCK_SCRAPER_CONFIG_PATH")
    if not config_path:
        if os.path.exists("config.yaml"):
            config_path = "config.yaml"
        elif os.path.exists("services/stock-scraper/config.yaml"):
            config_path = "services/stock-scraper/config.yaml"
        else:
            config_path = "config.yaml"
    if not os.path.exists(config_path):
        logger.error("Config not found at %s", config_path)
        return

    with open(config_path, "r") as f:
        config = yaml.safe_load(f) or {}

    symbols = config.get("symbols", [])
    timeframe = str(config.get("timeframe", "D"))
    range_bars = int(config.get("history_range", 200))
    backfill_pages = int(config.get("backfill_pages", 10))

    poll_interval = int(os.getenv("FA_STOCK_SCRAPER_POLL_INTERVAL", "300"))

    logger.info(
        "Starting Stock Scraper: %s symbols, timeframe=%s, range=%s, poll=%ss",
        len(symbols),
        timeframe,
        range_bars,
        poll_interval,
    )

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as http_session:
        while True:
            start_time = datetime.now(tz=timezone.utc)

            for symbol in symbols:
                if not isinstance(symbol, str) or not symbol.strip():
                    continue
                try:
                    await sync_symbol(
                        http_session, symbol, timeframe, range_bars, backfill_pages
                    )
                except Exception as exc:
                    logger.exception("Error syncing %s: %s", symbol, exc)

            elapsed = (datetime.now(tz=timezone.utc) - start_time).total_seconds()
            sleep_time = max(1, poll_interval - elapsed)
            await asyncio.sleep(sleep_time)


if __name__ == "__main__":
    asyncio.run(main())
