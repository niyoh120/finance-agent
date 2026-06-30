from datetime import date, datetime

from openbb_finance.router import baostock_available_for_range, route_index_price_sources, route_price_sources
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


def test_us_minute_routes_tdx_only():
    query = PriceQuery(symbol="AAPL", market="us", interval="1m")

    assert route_price_sources(query) == ["tdx"]


def test_hk_daily_routes_tdx_before_tickflow():
    query = PriceQuery(symbol="00700.HK", market="hk", interval="1d")

    assert route_price_sources(query) == ["tdx", "tickflow"]


def test_us_daily_routes_tdx_before_tickflow():
    query = PriceQuery(symbol="AAPL", market="us", interval="1d")

    assert route_price_sources(query) == ["tdx", "tickflow"]


def test_index_price_routes_cn_through_standard():
    query = PriceQuery(
        symbol="000001.XSHG",
        market="cn",
        end_date=date(2026, 4, 27),
        interval="1d",
    )
    sources = route_index_price_sources(query, now=datetime(2026, 4, 27, 16, 0))
    assert "tdx" in sources
    assert "tickflow" in sources


def test_index_price_routes_us_only_tdx():
    query = PriceQuery(
        symbol="SPX",
        market="us",
        end_date=date(2026, 4, 27),
        interval="1d",
    )
    sources = route_index_price_sources(query, now=datetime(2026, 4, 27, 16, 0))
    assert sources == ["tdx"]


def test_index_price_routes_hk_only_tdx():
    query = PriceQuery(
        symbol="HSI",
        market="hk",
        end_date=date(2026, 4, 27),
        interval="1d",
    )
    sources = route_index_price_sources(query, now=datetime(2026, 4, 27, 16, 0))
    assert sources == ["tdx"]
