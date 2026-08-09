"""Data source routing helpers."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from openbb_finance.sources.base import Market, PriceQuery, is_intraday_interval, normalize_interval
from openbb_finance.sources.symbols import INTL_FUTURES_EXCHANGES, futures_exchange


def is_trading_day(day: date) -> bool:
    return day.weekday() < 5


def _next_month_first(day: date) -> date:
    return (day.replace(day=1) + timedelta(days=32)).replace(day=1)


def baostock_available_for_range(
    data_type: str,
    start_date: date | None,
    end_date: date | None,
    *,
    now: datetime | None = None,
) -> bool:
    current = now or datetime.now()
    end = end_date or current.date()
    del start_date

    if data_type == "minute":
        if is_trading_day(end):
            return current >= datetime.combine(end, time(20, 0))
        return True

    if data_type == "daily":
        if is_trading_day(end):
            return current >= datetime.combine(end, time(17, 30))
        return True

    if data_type == "weekly":
        saturday = end + timedelta((5 - end.weekday()) % 7)
        return current >= datetime.combine(saturday, time(17, 30))

    if data_type == "monthly":
        return current >= datetime.combine(_next_month_first(end), time(17, 30))

    return False


def price_interval_type(interval: str) -> str:
    normalized = normalize_interval(interval)
    if is_intraday_interval(normalized):
        return "minute"
    if normalized.lower() in {"1w", "w"}:
        return "weekly"
    if normalized in {"1M", "1Q", "1Y"} or normalized.lower() in {"1mo", "1y"}:
        return "monthly"
    return "daily"


def route_price_sources(query: PriceQuery, *, now: datetime | None = None) -> list[str]:
    interval_type = price_interval_type(query.interval)
    market: Market = query.market

    if market == "cn":
        baostock_ready = baostock_available_for_range(
            interval_type,
            query.start_date,
            query.end_date,
            now=now,
        )
        if interval_type == "minute":
            fallback = ["baostock", "akshare"] if baostock_ready else ["akshare", "baostock"]
            return ["tdx", "tickflow", *fallback]
        if baostock_ready:
            return ["tdx", "tickflow", "baostock", "akshare"]
        return ["tdx", "tickflow", "akshare", "baostock"]

    if market in {"us", "hk"}:
        if interval_type == "minute":
            return ["tdx"]
        return ["tdx", "tickflow"]

    return ["openbb"]


def route_index_price_sources(query: PriceQuery, *, now: datetime | None = None) -> list[str]:
    """Route index historical price sources."""
    market: Market = query.market
    if market == "cn":
        return route_price_sources(query, now=now)
    return ["tdx"]


def route_futures_price_sources(query: PriceQuery) -> list[str]:
    """Route futures historical price sources: tdx primary, akshare fallback.

    - SGE spot-deferred products are tdx-only (akshare sina daily does not cover
      上海黄金交易所).
    - International exchanges (COMEX/NYMEX/CBOT) are tdx-only: the akshare sina
      daily endpoint only covers the five domestic commodity exchanges.
    - Intraday intervals are tdx-only (the sina daily fallback is daily bars).
    """
    exchange = futures_exchange(query.symbol)
    if is_intraday_interval(normalize_interval(query.interval)):
        return ["tdx"]
    if exchange in INTL_FUTURES_EXCHANGES or exchange == "SGE":
        return ["tdx"]
    return ["tdx", "akshare"]
