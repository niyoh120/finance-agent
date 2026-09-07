"""Live smoke tests against a running, authenticated schwab-api service.

Explicitly env-gated: these tests hit the real service at SCHWAB_API_BASE_URL
(default http://127.0.0.1:8010) and are skipped unless SCHWAB_LIVE_TEST=1, so
CI and plain `pytest` runs never touch the network.

Run with:
    SCHWAB_LIVE_TEST=1 uv run pytest -q openbb_finance/tests/test_schwab_live.py
"""

from __future__ import annotations

import os

import pytest
from openbb_finance.config import SourceConfig
from openbb_finance.sources.base import PriceQuery
from openbb_finance.sources.schwab import SchwabSource

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not os.environ.get("SCHWAB_LIVE_TEST"), reason="SCHWAB_LIVE_TEST not set"),
]


def _source() -> SchwabSource:
    base_url = os.environ.get("SCHWAB_API_BASE_URL") or "http://127.0.0.1:8010"
    api_key = os.environ.get("SCHWAB_API_KEY") or None
    return SchwabSource(SourceConfig(name="schwab", enabled=True, base_url=base_url, api_key=api_key))


async def test_live_quote():
    row = await _source().fetch_quote("AAPL")

    assert row["symbol"] == "AAPL"
    assert row["source"] == "schwab"
    assert row["last_price"] and row["last_price"] > 0
    assert row["prev_close"] and row["prev_close"] > 0


async def test_live_index_quote():
    row = await _source().fetch_quote("SPX")

    assert row["symbol"] == "SPX"
    assert row["last_price"] and row["last_price"] > 1000


async def test_live_historical_daily():
    rows = await _source().fetch_price(
        PriceQuery(symbol="AAPL", market="us", interval="1d", start_date=None, end_date=None)
    )

    assert rows, "expected daily candles"
    assert all(row["source"] == "schwab" for row in rows)
    assert rows[-1]["close"] > 0


async def test_live_historical_minute_extended():
    rows = await _source().fetch_price(
        PriceQuery(symbol="AAPL", market="us", interval="5m", extended=True)
    )

    assert rows, "expected minute candles"
    assert rows[0]["date"].hour >= 4  # extended-hours bar (04:00 ET onward)


async def test_live_search():
    rows = await _source().fetch_equity_search("apple", is_symbol=False)

    assert rows
    assert all(row["type"] == "EQUITY" for row in rows)


async def test_live_options_chain():
    source = _source()
    data = await source.fetch_options_chain("AAPL", dte=10, strike_count=5)

    assert data["contract_count"] > 0
    assert data["records"]
    record = data["records"][0]
    assert record["contract_symbol"] and record["contract_symbol"] == record["contract_symbol"].replace(" ", "")
    assert record["option_type"] in {"call", "put"}
    assert record["strike"] > 0
    assert record["dte"] <= 10
