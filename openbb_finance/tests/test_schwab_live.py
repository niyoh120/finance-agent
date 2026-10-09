"""Live smoke tests against a running, authenticated schwab-api service.

Explicitly env-gated: these tests hit the real service at SCHWAB_API_BASE_URL
(default http://127.0.0.1:8010) and are skipped unless SCHWAB_LIVE_TEST=1, so
CI and plain `pytest` runs never touch the network.

Run with:
    SCHWAB_LIVE_TEST=1 uv run pytest -q openbb_finance/tests/test_schwab_live.py
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

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
    rows = await _source().fetch_price(PriceQuery(symbol="AAPL", market="us", interval="5m", extended=True))

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


async def test_live_options_chain_date_window():
    """Date-window mode: absolute from_date/to_date push-down (CLI path).

    Uses a liquid sample and a wide strike budget so the assertion is about
    the request mode, not upstream strike coverage.
    """
    source = _source()
    today = datetime.now(timezone.utc).date()
    data = await source.fetch_options_chain(
        "AAPL", from_date=today, to_date=today + timedelta(days=45), strike_count=50
    )

    assert data["contract_count"] > 0
    assert data["records"]
    for record in data["records"]:
        assert record["expiration"] >= today
        assert record["expiration"] <= today + timedelta(days=45)


async def test_live_options_chain_date_window_strike_coverage():
    """Probe whether strike_count=atm pushes down enough candidates for the
    CLI's local ATM selection on a liquid underlying.

    Compares the distinct-strike count of a strike_count=20 request against a
    strike_count=60 reference on the same single-day window: if the narrow
    request already serves >= 20 distinct strikes per covered expiration,
    the raw pass-through covers the default CLI atm. Gaps are reported (not
    raised) so the probe documents upstream coverage limits.
    """
    source = _source()
    today = datetime.now(timezone.utc).date()
    window = (today + timedelta(days=20), today + timedelta(days=20))  # one listed expiration

    narrow = await source.fetch_options_chain("SPY", from_date=window[0], to_date=window[1], strike_count=20)
    reference = await source.fetch_options_chain("SPY", from_date=window[0], to_date=window[1], strike_count=60)

    narrow_strikes = {r["strike"] for r in narrow["records"]}
    reference_strikes = {r["strike"] for r in reference["records"]}
    print(
        f"strike coverage probe: narrow={len(narrow_strikes)} distinct strikes, "
        f"reference={len(reference_strikes)}, contract_count={narrow['contract_count']}"
    )
    # Informational: the CLI keeps atm=20 as the product cap; upstream shortfall
    # means fewer candidates than requested and must be surfaced via live runs.
    if len(narrow_strikes) < 20:
        pytest.fail(
            f"upstream strike_count=20 returned only {len(narrow_strikes)} distinct strikes; "
            "CLI atm selection may be candidate-starved"
        )
