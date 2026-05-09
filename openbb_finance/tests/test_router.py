from datetime import date, datetime

from openbb_finance.router import baostock_available_for_range, route_price_sources
from openbb_finance.sources.base import PriceQuery


def test_baostock_minute_available_for_previous_trading_day_next_morning():
    assert baostock_available_for_range(
        "minute",
        date(2026, 4, 24),
        date(2026, 4, 24),
        now=datetime(2026, 4, 27, 9, 0),
    )


def test_baostock_minute_unavailable_before_same_day_update():
    assert not baostock_available_for_range(
        "minute",
        date(2026, 4, 27),
        date(2026, 4, 27),
        now=datetime(2026, 4, 27, 19, 0),
    )


def test_cn_daily_routes_tickflow_before_baostock_update():
    query = PriceQuery(
        symbol="600519.XSHG",
        market="cn",
        end_date=date(2026, 4, 27),
        interval="1d",
    )

    assert route_price_sources(query, now=datetime(2026, 4, 27, 16, 0)) == [
        "tdx",
        "tickflow",
        "akshare",
        "baostock",
    ]


def test_cn_daily_routes_baostock_after_update():
    query = PriceQuery(
        symbol="600519.XSHG",
        market="cn",
        end_date=date(2026, 4, 27),
        interval="1d",
    )

    assert route_price_sources(query, now=datetime(2026, 4, 27, 18, 0)) == [
        "tdx",
        "tickflow",
        "baostock",
        "akshare",
    ]
