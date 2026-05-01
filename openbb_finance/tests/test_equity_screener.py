"""Tests for equity screener functionality."""

import asyncio
import sys
import types
from unittest.mock import AsyncMock

import pandas as pd
import pytest
from openbb_finance.models.equity_screener import (
    FinanceEquityScreenerData,
    FinanceEquityScreenerFetcher,
    FinanceEquityScreenerQueryParams,
)

from openbb_finance import provider


class FakeField:
    def __init__(self, name, label):
        self.name = name
        self.label = label

    def __ge__(self, value):
        return (">=", self.name, value)

    def __le__(self, value):
        return ("<=", self.name, value)

    def between(self, minimum, maximum):
        return ("between", self.name, minimum, maximum)

    def isin(self, values):
        return ("in", self.name, values)


class FakeMarket:
    AMERICA = "america"
    HONGKONG = "hongkong"
    CHINA = "china"
    ALL = "all"


class FakeStockField:
    DESCRIPTION = FakeField("DESCRIPTION", "Description")
    NAME = FakeField("NAME", "Name")
    PRICE = FakeField("PRICE", "Price")
    CHANGE_PERCENT = FakeField("CHANGE_PERCENT", "Change %")
    VOLUME = FakeField("VOLUME", "Volume")
    MARKET_CAPITALIZATION = FakeField("MARKET_CAPITALIZATION", "Market Capitalization")
    SECTOR = FakeField("SECTOR", "Sector")
    RELATIVE_STRENGTH_INDEX_14 = FakeField("RELATIVE_STRENGTH_INDEX_14", "Relative Strength Index (14)")
    EXPECTED_ANNUAL_DIVIDENDS = FakeField("EXPECTED_ANNUAL_DIVIDENDS", "Expected Annual Dividends")


class FakeStockScreener:
    last_instance = None

    def __init__(self):
        self.markets = [FakeMarket.AMERICA]
        self.range = [0, 150]
        self.selected = []
        self.filters = []
        FakeStockScreener.last_instance = self

    def set_markets(self, market):
        self.markets = [market]
        return self

    def set_range(self, start, end):
        self.range = [start, end]
        return self

    def select(self, *fields):
        self.selected = list(fields)
        return self

    def where(self, condition):
        self.filters.append(condition)
        return self

    def get(self):
        rows = [
            {
                "Symbol": "NASDAQ:AAPL",
                "Description": "Apple Inc.",
                "Name": "AAPL",
                "Price": 150.0,
                "Change %": 1.0,
                "Volume": 100,
                "Market Capitalization": 1_000_000.0,
                "Sector": "Technology",
                "Relative Strength Index (14)": 50.0,
                "Expected Annual Dividends": 1.23,
            }
        ]
        return pd.DataFrame(rows)


def install_fake_tvscreener(monkeypatch):
    fake_module = types.SimpleNamespace(
        Market=FakeMarket,
        StockField=FakeStockField,
        StockScreener=FakeStockScreener,
    )
    monkeypatch.setitem(sys.modules, "tvscreener", fake_module)
    FakeStockScreener.last_instance = None


def test_equity_screener_query_params_defaults():
    params = FinanceEquityScreenerQueryParams()
    assert params.market is None
    assert params.limit == 150
    assert params.price_min is None
    assert params.price_max is None
    assert params.change_percent_min is None
    assert params.change_percent_max is None
    assert params.volume_min is None
    assert params.volume_max is None
    assert params.market_cap_min is None
    assert params.market_cap_max is None
    assert params.rsi_min is None
    assert params.rsi_max is None
    assert params.sector is None


def test_equity_screener_query_params_with_values():
    params = FinanceEquityScreenerQueryParams(
        market="america",
        limit=50,
        price_min=50.0,
        price_max=200.0,
        change_percent_min=5.0,
        volume_min=1000000,
        sector=["Technology"],
    )
    assert params.market == "america"
    assert params.limit == 50
    assert params.price_min == 50.0
    assert params.price_max == 200.0
    assert params.change_percent_min == 5.0
    assert params.volume_min == 1000000
    assert params.sector == ["Technology"]


def test_equity_screener_query_params_accepts_sector_string():
    params = FinanceEquityScreenerQueryParams(sector="Technology")
    assert params.sector == "Technology"


def test_equity_screener_data_validation():
    data = FinanceEquityScreenerData(
        symbol="AAPL",
        name="Apple Inc.",
        price=150.0,
        change_percent=2.5,
        volume=1000000,
        market_cap=2500000000000,
        sector="Technology",
    )
    assert data.symbol == "AAPL"
    assert data.name == "Apple Inc."
    assert data.price == 150.0
    assert data.change_percent == 2.5


def test_screener_registered_in_provider():
    assert "EquityScreener" in provider.fetcher_dict
    assert provider.fetcher_dict["EquityScreener"] is FinanceEquityScreenerFetcher


def test_tradingview_applies_json_filter_for_common_field(monkeypatch):
    install_fake_tvscreener(monkeypatch)
    from openbb_finance.sources.tradingview import fetch_equity_screener

    asyncio.run(fetch_equity_screener(filters={"PRICE": {"min": 10000}}, limit=1))

    screener = FakeStockScreener.last_instance
    assert screener is not None
    assert (">=", "PRICE", 10000) in screener.filters


def test_tradingview_global_market_uses_all(monkeypatch):
    install_fake_tvscreener(monkeypatch)
    from openbb_finance.sources.tradingview import fetch_equity_screener

    asyncio.run(fetch_equity_screener(market="global", limit=1))

    screener = FakeStockScreener.last_instance
    assert screener is not None
    assert screener.markets == [FakeMarket.ALL]


def test_tradingview_sets_range_for_large_limit(monkeypatch):
    install_fake_tvscreener(monkeypatch)
    from openbb_finance.sources.tradingview import fetch_equity_screener

    asyncio.run(fetch_equity_screener(limit=500))

    screener = FakeStockScreener.last_instance
    assert screener is not None
    assert screener.range == [0, 500]


def test_tradingview_custom_fields_keep_symbol(monkeypatch):
    install_fake_tvscreener(monkeypatch)
    from openbb_finance.sources.tradingview import fetch_equity_screener

    result = asyncio.run(fetch_equity_screener(fields=["EXPECTED_ANNUAL_DIVIDENDS"], limit=1))

    screener = FakeStockScreener.last_instance
    assert screener is not None
    assert FakeStockField.EXPECTED_ANNUAL_DIVIDENDS in screener.selected
    assert result == [{"symbol": "NASDAQ:AAPL", "Expected Annual Dividends": 1.23}]


@pytest.mark.anyio
async def test_equity_screener_fetcher_with_filters(monkeypatch):
    mock_data = [
        {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "price": 150.0,
            "change_percent": 3.5,
            "volume": 50000000,
            "market_cap": 2500000000000,
            "sector": "Technology",
        },
        {
            "symbol": "MSFT",
            "name": "Microsoft Corporation",
            "price": 380.0,
            "change_percent": 4.2,
            "volume": 30000000,
            "market_cap": 2800000000000,
            "sector": "Technology",
        },
    ]

    extract_data = AsyncMock(return_value=mock_data)
    monkeypatch.setattr(provider.fetcher_dict["EquityScreener"], "extract_data", extract_data)

    result = await provider.fetcher_dict["EquityScreener"].fetch_data(
        {"market": "america", "limit": 50, "change_percent_min": 3.0},
        credentials=None,
    )

    assert len(result) == 2
    assert all(isinstance(row, FinanceEquityScreenerData) for row in result)
    assert result[0].symbol == "AAPL"
    assert result[1].symbol == "MSFT"
    extract_data.assert_awaited_once()


@pytest.mark.anyio
async def test_equity_screener_rejects_invalid_filter_json():
    query = FinanceEquityScreenerQueryParams(filters="x")

    with pytest.raises(ValueError, match="Invalid filters JSON"):
        await FinanceEquityScreenerFetcher.aextract_data(query, credentials=None)


@pytest.mark.anyio
async def test_equity_screener_splits_sector_string(monkeypatch):
    captured = {}

    async def fetch_equity_screener(**kwargs):
        captured.update(kwargs)
        return [{"symbol": "AAPL"}]

    monkeypatch.setattr(
        "openbb_finance.sources.tradingview.fetch_equity_screener",
        fetch_equity_screener,
    )

    query = FinanceEquityScreenerQueryParams(sector="Technology,Healthcare")
    await FinanceEquityScreenerFetcher.aextract_data(query, credentials=None)

    assert captured["sector"] == ["Technology", "Healthcare"]


@pytest.mark.anyio
async def test_tradingview_source_integration():
    """Integration test for TradingView source (requires network)."""
    pytest.skip("Integration test - requires network access to TradingView")

    from openbb_finance.sources.tradingview import fetch_equity_screener

    result = await fetch_equity_screener(
        market="america",
        change_percent_min=5.0,
        limit=5,
    )

    assert isinstance(result, list)
    assert len(result) <= 5
    if result:
        assert "symbol" in result[0]
