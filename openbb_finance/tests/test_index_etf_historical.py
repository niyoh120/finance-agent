"""Behavior tests for the finance index/ETF historical models.

Covers the shared input contract (asset-context symbol normalization, interval
canonicalization with per-market capability bounds) and the per-source intraday
quality gate inside the fetch loop.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock

import pytest
from openbb_core.provider.utils.errors import EmptyDataError
from openbb_finance.models._historical_query import validate_intraday_rows
from openbb_finance.models.etf_historical import (
    FinanceEtfHistoricalFetcher,
    FinanceEtfHistoricalQueryParams,
)
from openbb_finance.models.index_historical import (
    FinanceIndexHistoricalFetcher,
    FinanceIndexHistoricalQueryParams,
)

# --------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------- #


def _bar(day_time: datetime | date, close: float = 1.5, **overrides) -> dict:
    row = {
        "date": day_time,
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": close,
        "volume": 10,
        "symbol": "000300.XSHG",
        "source": "fake",
    }
    row.update(overrides)
    return row


def _minute_rows(**overrides) -> list[dict]:
    times = [
        datetime(2026, 9, 18, 9, 31),
        datetime(2026, 9, 18, 9, 32),
        datetime(2026, 9, 18, 9, 33),
    ]
    return [_bar(t, **overrides) for t in times]


class _FakeSource:
    def __init__(self, name: str, rows: list[dict] | None = None, error: Exception | None = None) -> None:
        self.name = name
        self.enabled = True
        self.fetch_price = AsyncMock(return_value=rows) if error is None else AsyncMock(side_effect=error)

    def fetch_quote(self, symbol: str) -> dict:  # pragma: no cover - shape only
        raise NotImplementedError


class _FakeRegistry:
    def __init__(self, *sources: _FakeSource) -> None:
        self._sources = {source.name: source for source in sources}
        self.requested: list[list[str]] = []

    def ordered_by_names(self, names: list[str]):
        self.requested.append(list(names))
        return [self._sources[name] for name in names if name in self._sources]


async def _fetch(fetcher, query) -> list[dict]:
    return await fetcher.aextract_data(query, credentials=None, registry=_FakeRegistry())


# --------------------------------------------------------------------- #
# Symbol contract
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("  000300.sh ", "000300.XSHG"),
        ("000300.SS", "000300.XSHG"),
        ("000300.XSHG", "000300.XSHG"),
        ("399006.sz", "399006.XSHE"),
        ("$SPX", "SPX"),
        (" hsi ", "HSI"),
    ],
)
def test_index_symbol_canonicalization(raw, canonical):
    query = FinanceIndexHistoricalFetcher.transform_query({"symbol": raw})
    assert query.symbol == canonical


@pytest.mark.parametrize(
    "raw",
    [
        "000001",  # bare CN index code: ambiguous (index vs stock)
        "000300.BAD",  # unknown suffix must not become a US ticker
        "899050.BJ",  # unconnected exchange
        "FOO",  # unknown identity must not enter the stock market chain
        "",
        "SPY,QQQ",  # multi-symbol input stays unsupported
    ],
)
def test_index_symbol_rejections(raw):
    with pytest.raises(ValueError):
        FinanceIndexHistoricalQueryParams(symbol=raw)


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("510300", "510300.XSHG"),  # bare CN ETF keeps market inference
        ("159915", "159915.XSHE"),
        (" 510300.sh ", "510300.XSHG"),
        ("spy", "SPY"),
        ("brk.b", "BRK.B"),  # dotted US ticker stays whole
        ("02800.HK", "02800.HK"),
        ("02800", "02800"),  # bare five-digit HK code infers hk
    ],
)
def test_etf_symbol_canonicalization(raw, canonical):
    query = FinanceEtfHistoricalFetcher.transform_query({"symbol": raw})
    assert query.symbol == canonical


@pytest.mark.parametrize(
    "raw",
    [
        "000300.BAD",
        "899050.BJ",
        "2800",  # bare 4-digit digit code would infer the US market
        "GOOG.XSHG",  # exchange suffix on an alphabetic code
        "",
        "510300,159915",
    ],
)
def test_etf_symbol_rejections(raw):
    with pytest.raises(ValueError):
        FinanceEtfHistoricalQueryParams(symbol=raw)


# --------------------------------------------------------------------- #
# Interval contract
# --------------------------------------------------------------------- #


def test_interval_defaults_to_daily():
    assert FinanceIndexHistoricalFetcher.transform_query({"symbol": "SPX"}).interval == "1d"
    assert FinanceEtfHistoricalFetcher.transform_query({"symbol": "510300"}).interval == "1d"


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [("5m", "5m"), ("1h", "60m"), ("1H", "60m"), ("60", "60m"), ("1d", "1d"), ("1w", "1w"), ("1M", "1M")],
)
def test_interval_aliases(raw, canonical):
    assert FinanceIndexHistoricalQueryParams(symbol="SPX", interval=raw).interval == canonical


def test_us_extra_10m_accepted():
    assert FinanceIndexHistoricalQueryParams(symbol="SPX", interval="10m").interval == "10m"


@pytest.mark.parametrize(
    ("symbol", "interval"),
    [
        ("000300.XSHG", "10m"),  # CN has no 10m capability
        ("HSI", "10m"),  # HK has no 10m capability
        ("SPX", "7m"),  # unknown granularity
        ("SPX", ""),  # empty
        ("SPX", "2h"),
    ],
)
def test_interval_rejections(symbol, interval):
    with pytest.raises(ValueError):
        FinanceIndexHistoricalQueryParams(symbol=symbol, interval=interval)


# --------------------------------------------------------------------- #
# Intraday quality gate
# --------------------------------------------------------------------- #


def test_quality_gate_accepts_legit_sequences():
    validate_intraday_rows(_minute_rows(), symbol="000300.XSHG", interval="1m")
    # A single legitimate midnight bar stays allowed.
    validate_intraday_rows([_bar(datetime(2026, 9, 18, 0, 0))], symbol="S", interval="1m")
    # US sessions cross midnight in source time; ascending order is what counts.
    validate_intraday_rows(
        [_bar(datetime(2026, 9, 18, 23, 55)), _bar(datetime(2026, 9, 19, 0, 0))],
        symbol="SPY",
        interval="5m",
    )


@pytest.mark.parametrize(
    "rows",
    [
        [_bar(date(2026, 9, 18))],  # date-only row leaked into a minute result
        [_bar(datetime(2026, 9, 18, 9, 31)), _bar(datetime(2026, 9, 18, 9, 31))],  # duplicate stamp
        [_bar(datetime(2026, 9, 18, 9, 32)), _bar(datetime(2026, 9, 18, 9, 31))],  # descending
        [_bar(datetime(2026, 9, 18, 0, 0)) for _ in range(3)],  # collapsed onto midnight
    ],
)
def test_quality_gate_rejections(rows):
    with pytest.raises(ValueError):
        validate_intraday_rows(rows, symbol="X", interval="1m")


# --------------------------------------------------------------------- #
# Fetch-loop routing and fallback
# --------------------------------------------------------------------- #


@pytest.mark.anyio
async def test_minute_result_from_schwab_wins():
    schwab_rows = [_bar(t, source="schwab") for t in (datetime(2026, 9, 18, 9, 31), datetime(2026, 9, 18, 9, 32))]
    tdx_rows = [_bar(t, source="tdx") for t in (datetime(2026, 9, 18, 21, 31),)]
    registry = _FakeRegistry(_FakeSource("schwab", schwab_rows), _FakeSource("tdx", tdx_rows))
    query = FinanceIndexHistoricalFetcher.transform_query({"symbol": "SPX", "interval": "1m"})

    data = await FinanceIndexHistoricalFetcher.aextract_data(query, credentials=None, registry=registry)

    assert data == schwab_rows
    assert registry.requested == [["schwab", "tdx"]]


@pytest.mark.anyio
async def test_schwab_failure_falls_back_to_tdx():
    tdx_rows = [_bar(t, source="tdx") for t in (datetime(2026, 9, 18, 21, 31), datetime(2026, 9, 18, 21, 32))]
    registry = _FakeRegistry(_FakeSource("schwab", error=RuntimeError("down")), _FakeSource("tdx", tdx_rows))
    query = FinanceIndexHistoricalFetcher.transform_query({"symbol": "SPX", "interval": "1m"})

    data = await FinanceIndexHistoricalFetcher.aextract_data(query, credentials=None, registry=registry)

    assert data == tdx_rows


@pytest.mark.anyio
async def test_invalid_minute_result_is_not_served_as_fallback():
    """A source whose minute bars fail the quality gate must be skipped."""
    collapsed = [_bar(datetime(2026, 9, 18, 0, 0)) for _ in range(5)]  # TDX 1m defect shape
    valid = [_bar(datetime(2026, 9, 18, 9, 31), source="tdx")]
    registry = _FakeRegistry(_FakeSource("schwab", collapsed), _FakeSource("tdx", valid))
    query = FinanceIndexHistoricalFetcher.transform_query({"symbol": "SPX", "interval": "1m"})

    data = await FinanceIndexHistoricalFetcher.aextract_data(query, credentials=None, registry=registry)

    assert data == valid


@pytest.mark.anyio
async def test_all_sources_fail_returns_empty():
    registry = _FakeRegistry(_FakeSource("schwab", error=RuntimeError("down")), _FakeSource("tdx", []))
    query = FinanceIndexHistoricalFetcher.transform_query({"symbol": "SPX", "interval": "1m"})

    data = await FinanceIndexHistoricalFetcher.aextract_data(query, credentials=None, registry=registry)

    assert data == []


@pytest.mark.anyio
async def test_cn_etf_minute_chain_is_tdx_only():
    registry = _FakeRegistry(_FakeSource("tdx", _minute_rows(source="tdx")))
    query = FinanceEtfHistoricalFetcher.transform_query({"symbol": "510300", "interval": "5m"})

    data = await FinanceEtfHistoricalFetcher.aextract_data(query, credentials=None, registry=registry)

    assert registry.requested == [["tdx"]]
    assert data[0]["source"] == "tdx"


@pytest.mark.anyio
async def test_daily_result_bypasses_minute_quality_gate():
    """The 1d chain keeps its existing behaviour: date-typed rows win."""
    daily = [_bar(date(2026, 9, 17)), _bar(date(2026, 9, 18))]
    registry = _FakeRegistry(_FakeSource("schwab", daily), _FakeSource("tdx", []))
    query = FinanceIndexHistoricalFetcher.transform_query({"symbol": "SPX", "interval": "1d"})

    data = await FinanceIndexHistoricalFetcher.aextract_data(query, credentials=None, registry=registry)

    assert data == daily


# --------------------------------------------------------------------- #
# transform_data: standard model date semantics
# --------------------------------------------------------------------- #


def test_index_transform_keeps_minute_datetime_and_daily_date():
    query = FinanceIndexHistoricalFetcher.transform_query({"symbol": "000300.XSHG", "interval": "5m"})
    minute_dt = datetime(2026, 9, 18, 9, 35)
    rows = [
        {"symbol": "000300.XSHG", "date": minute_dt, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10}
    ]

    result = FinanceIndexHistoricalFetcher.transform_data(query, rows)

    assert result[0].date == minute_dt
    assert isinstance(result[0].date, datetime)

    daily_rows = [{**rows[0], "date": date(2026, 9, 18)}]
    result = FinanceIndexHistoricalFetcher.transform_data(query, daily_rows)
    assert result[0].date == date(2026, 9, 18)


def test_index_transform_empty_raises_empty_data():
    query = FinanceIndexHistoricalFetcher.transform_query({"symbol": "SPX"})
    with pytest.raises(EmptyDataError):
        FinanceIndexHistoricalFetcher.transform_data(query, [])


def test_etf_transform_keeps_minute_datetime():
    query = FinanceEtfHistoricalFetcher.transform_query({"symbol": "510300", "interval": "5m"})
    minute_dt = datetime(2026, 9, 18, 9, 35)
    rows = [{"date": minute_dt, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}]

    result = FinanceEtfHistoricalFetcher.transform_data(query, rows)

    assert result[0].date == minute_dt
