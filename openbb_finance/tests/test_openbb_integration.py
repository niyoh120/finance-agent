from datetime import date
from unittest.mock import AsyncMock

import pytest
from openbb import obb
from openbb_finance.models.equity_historical import FinanceEquityHistoricalData
from openbb_finance.models.equity_quote import FinanceEquityQuoteData
from openbb_finance.models.equity_search import FinanceEquitySearchData
from openbb_finance.models.technical_indicators import FinanceTechnicalIndicatorsData
from openbb_finance.models.world_news import FinanceWorldNewsFetcher

from openbb_finance import provider


def test_finance_provider_registered_in_openbb_coverage():
    assert "finance" in obb.coverage.providers
    assert ".equity.price.historical" in obb.coverage.providers["finance"]
    assert ".equity.price.quote" in obb.coverage.providers["finance"]
    assert ".equity.search" in obb.coverage.providers["finance"]
    assert ".index.price.historical" in obb.coverage.providers["finance"]
    assert ".etf.historical" in obb.coverage.providers["finance"]
    assert ".economy.calendar" in obb.coverage.providers["finance"]
    assert ".news.company" in obb.coverage.providers["finance"]
    assert ".news.world" in obb.coverage.providers["finance"]
    assert ".derivatives.options.unusual" in obb.coverage.providers["finance"]
    assert provider.fetcher_dict["WorldNews"] is FinanceWorldNewsFetcher
    assert hasattr(obb.technical, "indicators")
    assert ".technical.indicators" in obb.coverage.providers["finance"]


@pytest.mark.anyio
async def test_equity_historical_fetcher_interface(monkeypatch):
    raw_payload = [
        {
            "date": date(2026, 4, 24),
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "volume": 100,
            "symbol": "600519.XSHG",
            "source": "integration-test",
        }
    ]
    extract_data = AsyncMock(return_value=raw_payload)
    monkeypatch.setattr(provider.fetcher_dict["EquityHistorical"], "extract_data", extract_data)

    result = await provider.fetcher_dict["EquityHistorical"].fetch_data(
        {"symbol": "600519.XSHG"},
        credentials=None,
    )

    assert len(result) == 1
    row = result[0]
    assert isinstance(row, FinanceEquityHistoricalData)
    assert row.symbol == "600519.XSHG"
    assert row.source == "integration-test"
    extract_data.assert_awaited_once()


@pytest.mark.anyio
async def test_equity_quote_fetcher_interface(monkeypatch):
    extract_data = AsyncMock(
        return_value=[
            {
                "symbol": "600519.XSHG",
                "last_price": 100.0,
                "source": "integration-test",
            }
        ]
    )
    monkeypatch.setattr(provider.fetcher_dict["EquityQuote"], "extract_data", extract_data)

    result = await provider.fetcher_dict["EquityQuote"].fetch_data(
        {"symbol": "600519.XSHG"},
        credentials=None,
    )

    assert len(result) == 1
    row = result[0]
    assert isinstance(row, FinanceEquityQuoteData)
    assert row.symbol == "600519.XSHG"
    assert row.source == "integration-test"
    extract_data.assert_awaited_once()


@pytest.mark.anyio
async def test_equity_search_fetcher_interface(monkeypatch):
    extract_data = AsyncMock(
        return_value=[
            {
                "symbol": "600519.XSHG",
                "name": "贵州茅台",
                "source": "integration-test",
            }
        ]
    )
    monkeypatch.setattr(provider.fetcher_dict["EquitySearch"], "extract_data", extract_data)

    result = await provider.fetcher_dict["EquitySearch"].fetch_data(
        {"query": "茅台"},
        credentials=None,
    )

    assert len(result) == 1
    row = result[0]
    assert isinstance(row, FinanceEquitySearchData)
    assert row.symbol == "600519.XSHG"
    assert row.source == "integration-test"
    extract_data.assert_awaited_once()


@pytest.mark.anyio
async def test_index_historical_fetcher_interface(monkeypatch):
    extract_data = AsyncMock(
        return_value=[
            {
                "symbol": "000001.XSHG",
                "date": date(2026, 4, 24),
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 100,
            }
        ]
    )
    monkeypatch.setattr(provider.fetcher_dict["IndexHistorical"], "extract_data", extract_data)

    result = await provider.fetcher_dict["IndexHistorical"].fetch_data(
        {"symbol": "000001.XSHG"},
        credentials=None,
    )

    assert len(result) == 1
    assert result[0].symbol == "000001.XSHG"
    extract_data.assert_awaited_once()


@pytest.mark.anyio
async def test_etf_historical_fetcher_interface(monkeypatch):
    extract_data = AsyncMock(
        return_value=[
            {
                "date": date(2026, 4, 24),
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 100,
            }
        ]
    )
    monkeypatch.setattr(provider.fetcher_dict["EtfHistorical"], "extract_data", extract_data)

    result = await provider.fetcher_dict["EtfHistorical"].fetch_data(
        {"symbol": "510300.XSHG"},
        credentials=None,
    )

    assert len(result) == 1
    assert result[0].close == 1.5
    extract_data.assert_awaited_once()


def test_technical_indicators_openbb_route(monkeypatch):
    extract_data = AsyncMock(
        return_value=[
            {
                "date": date(2026, 4, 24),
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 100,
                "symbol": "600519.XSHG",
                "source": "integration-test",
                "rsi": 55.0,
                "vwap": 1.3,
            }
        ]
    )
    monkeypatch.setattr(provider.fetcher_dict["TechnicalIndicators"], "extract_data", extract_data)

    result = obb.technical.indicators(
        symbol="600519.XSHG",
        indicators=["rsi", "vwap"],
        provider="finance",
    )

    assert len(result.results) == 1
    row = result.results[0]
    assert isinstance(row, FinanceTechnicalIndicatorsData)
    assert row.symbol == "600519.XSHG"
    assert row.rsi == 55.0
    assert row.vwap == 1.3
    extract_data.assert_awaited_once()


def test_technical_indicators_openbb_route_respects_output_type(monkeypatch):
    extract_data = AsyncMock(
        return_value=[
            {
                "date": date(2026, 4, 24),
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 100,
                "symbol": "600519.XSHG",
                "source": "integration-test",
                "rsi": 55.0,
            }
        ]
    )
    monkeypatch.setattr(provider.fetcher_dict["TechnicalIndicators"], "extract_data", extract_data)
    monkeypatch.setattr(obb.user.preferences, "output_type", "dataframe")

    result = obb.technical.indicators(
        symbol="600519.XSHG",
        indicators=["rsi"],
        provider="finance",
    )

    assert result.iloc[0]["symbol"] == "600519.XSHG"
    assert result.iloc[0]["rsi"] == 55.0
