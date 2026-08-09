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


@pytest.mark.anyio
async def test_futures_historical_fetcher_interface(monkeypatch):
    from openbb_finance.models.futures_historical import FinanceFuturesHistoricalData

    raw_payload = [
        {
            "date": date(2026, 4, 24),
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "volume": 100,
            "symbol": "RB.SHFE",
            "source": "integration-test",
        }
    ]
    extract_data = AsyncMock(return_value=raw_payload)
    monkeypatch.setattr(provider.fetcher_dict["FuturesHistorical"], "extract_data", extract_data)

    result = await provider.fetcher_dict["FuturesHistorical"].fetch_data(
        {"symbol": "rb.SHFE", "expiration": "2026-10"},
        credentials=None,
    )

    assert len(result) == 1
    row = result[0]
    assert isinstance(row, FinanceFuturesHistoricalData)
    assert row.symbol == "RB.SHFE"
    assert row.close == 1.5
    assert row.source == "integration-test"
    extract_data.assert_awaited_once()


@pytest.mark.anyio
async def test_futures_quote_fetcher_interface(monkeypatch):
    from openbb_finance.models.futures_quote import FinanceFuturesQuoteData

    extract_data = AsyncMock(
        return_value=[
            {
                "symbol": "GC.COMEX",
                "name": "COMEX黄金主连",
                "last_price": 4401.3,
                "source": "integration-test",
            }
        ]
    )
    monkeypatch.setattr(provider.fetcher_dict["FuturesQuote"], "extract_data", extract_data)

    result = await provider.fetcher_dict["FuturesQuote"].fetch_data(
        {"symbol": "GC.COMEX"},
        credentials=None,
    )

    assert len(result) == 1
    row = result[0]
    assert isinstance(row, FinanceFuturesQuoteData)
    assert row.symbol == "GC.COMEX"
    assert row.last_price == 4401.3
    extract_data.assert_awaited_once()


@pytest.mark.anyio
async def test_futures_search_fetcher_interface(monkeypatch):
    from openbb_finance.models.futures_search import FinanceFuturesSearchData

    extract_data = AsyncMock(
        return_value=[
            {
                "symbol": "SI.GFEX",
                "expiration": "2026-09",
                "code": "SI2609",
                "name": "工业硅2609",
                "exchange": "GFEX",
                "source": "integration-test",
            }
        ]
    )
    monkeypatch.setattr(provider.fetcher_dict["FuturesSearch"], "extract_data", extract_data)

    result = await provider.fetcher_dict["FuturesSearch"].fetch_data(
        {"query": "si", "is_symbol": True},
        credentials=None,
    )

    assert len(result) == 1
    row = result[0]
    assert isinstance(row, FinanceFuturesSearchData)
    assert row.symbol == "SI.GFEX"
    assert row.expiration == "2026-09"
    assert row.exchange == "GFEX"
    extract_data.assert_awaited_once()


def test_futures_models_registered_in_provider_interface():
    from openbb_core.app.provider_interface import ProviderInterface

    pi = ProviderInterface()
    assert "FuturesHistorical" in pi.params
    assert "FuturesQuote" in pi.params
    assert "FuturesSearch" in pi.params
    # The standard model fields are recognized for FuturesHistorical.
    assert {"symbol", "start_date", "end_date", "expiration"} <= {
        name for name in pi.params["FuturesHistorical"]["standard"].__dataclass_fields__
    }


@pytest.mark.anyio
async def test_futures_historical_fetcher_unlisted_month_raises_empty(monkeypatch):
    """An unlisted month contract must surface as EmptyDataError, not silent empty.

    Unit-level check: transform_data([]) raises EmptyDataError so the CLI surfaces
    EMPTY_DATA instead of an empty result list.
    """

    from openbb_core.provider.utils.errors import EmptyDataError
    from openbb_finance.models.futures_historical import FinanceFuturesHistoricalFetcher

    query = FinanceFuturesHistoricalFetcher.transform_query(
        {"symbol": "IF.CFFEX", "expiration": "2026-10"}
    )
    with pytest.raises(EmptyDataError):
        FinanceFuturesHistoricalFetcher.transform_data(query, [])
