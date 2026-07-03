from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from openbb_core.provider.utils.errors import EmptyDataError
from openbb_finance.models.options_unusual import (
    FinanceOptionsUnusualData,
    FinanceOptionsUnusualFetcher,
    FinanceOptionsUnusualQueryParams,
)

from openbb_finance import provider


def test_query_defaults_date_range():
    query = FinanceOptionsUnusualQueryParams()

    assert query.start_date is not None
    assert query.end_date is not None
    assert query.start_date <= query.end_date


def test_transform_data_maps_payload():
    payload = [
        {
            "symbol": "AAPL",
            "contract_symbol": "AAPL250117C00200000",
            "timestamp": datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
            "sentiment": "bullish",
            "avg_fill": 3.25,
            "premium": 100000.0,
            "strike": 200.0,
            "option_type": "C",
            "expiration": date(2025, 1, 17),
            "dte": 16,
            "side": "Bid",
            "interval_volume": 1200,
            "open_interest": 100,
            "vol_oi": 12.0,
            "otm_percent": 0.1,
            "bid_percent": 60,
            "ask_percent": 40,
            "multileg_percent": 0.2,
            "interval_type": "5Min",
        }
    ]

    result = FinanceOptionsUnusualFetcher.transform_data(FinanceOptionsUnusualQueryParams(), payload)

    assert len(result) == 1
    row = result[0]
    assert isinstance(row, FinanceOptionsUnusualData)
    assert row.underlying_symbol == "AAPL"
    assert row.trade_timestamp == payload[0]["timestamp"]
    assert row.total_value == 100000.0


def test_transform_data_empty_raises():
    with pytest.raises(EmptyDataError):
        FinanceOptionsUnusualFetcher.transform_data(FinanceOptionsUnusualQueryParams(), [])


@pytest.mark.anyio
async def test_aextract_data_uses_mock_db(monkeypatch):
    row = SimpleNamespace(
        symbol="AAPL",
        expiry=date(2025, 1, 17),
        option_type="C",
        strike=200.0,
        timestamp=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
        side="Bid",
        avg_fill=3.25,
        premium=100000.0,
        dte=16,
        interval_volume=1200,
        open_interest=100,
        vol_oi=12.0,
        otm_percent=0.1,
        bid_percent=60,
        ask_percent=40,
        multileg_percent=0.2,
        interval_type="5Min",
    )

    execute = AsyncMock()
    execute.return_value = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [row]),
    )

    class FakeSession:
        async def execute(self, stmt):
            return await execute(stmt)

    class FakeSessionScope:
        async def __aenter__(self):
            return FakeSession()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "openbb_finance.models.options_unusual.session_scope",
        lambda: FakeSessionScope(),
    )

    query = FinanceOptionsUnusualQueryParams(symbol="AAPL")
    data = await FinanceOptionsUnusualFetcher.aextract_data(query, credentials=None)

    assert len(data) == 1
    assert data[0]["symbol"] == "AAPL"
    assert data[0]["contract_symbol"] == "AAPL250117C00200000"
    # Call @ Bid -> seller aggressor -> bearish (see _infer_sentiment)
    assert data[0]["sentiment"] == "bearish"
    execute.assert_awaited_once()


@pytest.mark.anyio
async def test_fetch_data_via_openbb_fetcher_interface(monkeypatch):
    raw_payload = [
        {
            "symbol": "TSLA",
            "contract_symbol": "TSLA250117P00250000",
            "timestamp": datetime(2025, 1, 2, 11, 0, tzinfo=UTC),
            "sentiment": "bearish",
            "avg_fill": 4.5,
            "premium": 250000.0,
            "strike": 250.0,
            "option_type": "P",
            "expiration": date(2025, 1, 17),
            "dte": 15,
            "side": "Ask",
            "interval_volume": 800,
            "open_interest": 50,
            "vol_oi": 16.0,
            "otm_percent": 0.08,
            "bid_percent": 35,
            "ask_percent": 65,
            "multileg_percent": 0.1,
            "interval_type": "5Min",
        }
    ]

    monkeypatch.setattr(
        provider.fetcher_dict["OptionsUnusual"],
        "extract_data",
        AsyncMock(return_value=raw_payload),
    )

    result = await provider.fetcher_dict["OptionsUnusual"].fetch_data(
        {"symbol": "TSLA"},
        credentials=None,
    )

    assert len(result) == 1
    assert isinstance(result[0], FinanceOptionsUnusualData)
    assert result[0].underlying_symbol == "TSLA"
    assert result[0].side == "Ask"
    assert result[0].total_value == 250000.0
