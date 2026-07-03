"""Tests for the ConvexValue data source and its provider models.

Covers:
- sources/convexvalue.py: header construction, 502 retry, 4xx raise, JSON parse
- equity_options_chain.py: [strike, call[], put[]] triplet flattening
- equity_options_screener.py: predefined predicate -> CV filter conversion
- equity_options_query.py: SQL pass-through and row shaping
- income_statement.py: FMP camelCase -> openbb snake_case alias mapping
- config.py: convexvalue source registration with ${CV_API_KEY}
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from openbb_finance.config import DEFAULT_PRIORITIES, get_source_config
from openbb_finance.models.equity_options_chain import (
    FinanceOptionsChainFetcher,
    _flatten_chain,
)
from openbb_finance.models.equity_options_query import FinanceOptionsQueryFetcher
from openbb_finance.models.equity_options_screener import (
    FinanceOptionsScreenerQueryParams,
    _build_filters,
)
from openbb_finance.models.income_statement import FinanceIncomeStatementFetcher
from openbb_finance.sources import convexvalue as cv

pytestmark = pytest.mark.anyio


# ---------- source client ----------

class _StubResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload) if isinstance(payload, (dict, list)) else str(payload)

    def json(self) -> Any:
        return self._payload


class _StubClient:
    """httpx.AsyncClient stand-in that returns canned responses in order."""

    def __init__(self, responses: list[_StubResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> "_StubClient":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any]) -> _StubResponse:
        self.calls.append({"url": url, "headers": headers, "json": json})
        if not self._responses:
            raise AssertionError("no more stub responses")
        return self._responses.pop(0)


async def test_post_sets_bearer_auth_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CV_API_KEY", "test-key-123")
    stub = _StubClient([_StubResponse(200, {"ok": True})])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: stub)

    await cv._post("chains", {"symbol": "SPY"})

    call = stub.calls[0]
    assert call["headers"]["Authorization"] == "Bearer test-key-123"
    assert call["headers"]["User-Agent"] == "cv-preview-node/0.1"
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["url"].endswith("/chains")


async def test_post_raises_on_4xx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CV_API_KEY", "k")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _StubClient([_StubResponse(422, {"error": "bad"})]))
    with pytest.raises(cv.ConvexValueError, match="422"):
        await cv._post("chains", {})


async def test_post_retries_502_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CV_API_KEY", "k")
    # FMP upstream intermittently 502s; client should retry then succeed.

    async def _no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(cv.asyncio, "sleep", _no_sleep)
    stub = _StubClient([
        _StubResponse(502, "<html>error</html>"),
        _StubResponse(200, {"rows": []}),
    ])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: stub)
    result = await cv._post("query", {"sql": "SELECT 1"})
    assert result == {"rows": []}
    assert len(stub.calls) == 2


async def test_post_raises_after_exhausting_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CV_API_KEY", "k")

    async def _no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(cv.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **_: _StubClient([_StubResponse(502, "x"), _StubResponse(502, "x"), _StubResponse(502, "x")]),
    )
    with pytest.raises(cv.ConvexValueError, match="502"):
        await cv._post("query", {})


async def test_post_raises_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CV_API_KEY", raising=False)
    with pytest.raises(cv.ConvexValueError, match="CV_API_KEY"):
        await cv._post("chains", {})


# ---------- options chain flattening ----------

def test_flatten_chain_expands_triplets() -> None:
    # Build field arrays in the real CHAIN_FIELDS order so indices line up.
    fields_idx = {name: i for i, name in enumerate(cv.CHAIN_FIELDS)}

    def make_row(contract_type: str, delta: float | None, oi: float | None) -> list[Any]:
        row = [None] * len(cv.CHAIN_FIELDS)
        row[fields_idx["expiration_date"]] = "2026-07-17"
        row[fields_idx["strike_price"]] = 500.0
        row[fields_idx["contract_type"]] = contract_type
        row[fields_idx["delta"]] = delta
        row[fields_idx["open_interest"]] = oi
        row[fields_idx["ticker"]] = "O:SPY260717C00500000" if contract_type == "call" else "O:SPY260717P00500000"
        return row

    raw = {
        "symbol": "SPY",
        "chain": [
            {
                "expiration": "2026-07-17",
                "strikes": [
                    [500.0, make_row("call", 0.5, None), make_row("put", None, 100.0)],
                    # Illiquid strike: both sides all-None -> skipped
                    [999.0, [None] * len(cv.CHAIN_FIELDS), [None] * len(cv.CHAIN_FIELDS)],
                ],
            },
        ],
    }
    records = _flatten_chain(raw)
    # Two records (call + put) from the first strike; illiquid strike dropped.
    assert len(records) == 2
    call = next(r for r in records if r["option_type"] == "call")
    put = next(r for r in records if r["option_type"] == "put")
    assert call["strike"] == 500.0
    assert call["delta"] == 0.5
    assert put["strike"] == 500.0
    assert put["open_interest"] == 100.0


def test_flatten_chain_empty_symbol_returns_empty() -> None:
    # CV returns HTTP 200 with empty chain for unknown symbols.
    assert _flatten_chain({"symbol": "FAKE", "chain": []}) == []


# ---------- options screener filter conversion ----------

def test_build_filters_translates_predicates() -> None:
    q = FinanceOptionsScreenerQueryParams(
        underlying_symbol="spy",
        option_type="CALL",  # case-insensitive acceptance
        min_open_interest=1000,
        max_iv=0.5,
        delta_min=-0.5,
        delta_max=-0.2,
    )
    filters = _build_filters(q)
    by_field = {f["field"]: f for f in filters if f["field"] != "delta"}
    delta_filters = [f for f in filters if f["field"] == "delta"]
    assert by_field["underlying_ticker"] == {"field": "underlying_ticker", "op": "eq", "value": "SPY"}
    assert by_field["contract_type"]["value"] == "call"
    assert by_field["open_interest"]["op"] == "gte"
    assert by_field["implied_volatility"]["op"] == "lte" and by_field["implied_volatility"]["value"] == 0.5
    assert {f["op"]: f["value"] for f in delta_filters} == {"gte": -0.5, "lte": -0.2}


def test_build_filters_merges_extra_filters() -> None:
    q = FinanceOptionsScreenerQueryParams(
        min_open_interest=500,
        extra_filters=[{"field": "day_volume", "op": "gt_field", "value": "open_interest"}],
    )
    filters = _build_filters(q)
    assert any(f == {"field": "day_volume", "op": "gt_field", "value": "open_interest"} for f in filters)


def test_build_filters_empty_when_no_predicates() -> None:
    q = FinanceOptionsScreenerQueryParams()
    assert _build_filters(q) == []


# ---------- options query ----------

async def test_options_query_passthrough_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CV_API_KEY", "k")
    captured: dict[str, Any] = {}

    async def fake_query(sql: str, max_rows: int | None = None) -> dict[str, Any]:
        captured["sql"] = sql
        captured["max_rows"] = max_rows
        return {
            "rows": [{"underlying_ticker": "SPY", "gex": 123.0}],
            "row_count": 1, "truncated": False, "elapsed_ms": 5,
        }

    monkeypatch.setattr(cv, "fetch_query", fake_query)

    q = FinanceOptionsQueryFetcher.transform_query({"sql": "SELECT 1"})
    raw = await FinanceOptionsQueryFetcher.aextract_data(q, None)
    data = FinanceOptionsQueryFetcher.transform_data(q, raw)
    assert captured["sql"] == "SELECT 1"
    assert data[0].row_count == 1
    assert data[0].rows[0]["underlying_ticker"] == "SPY"


# ---------- income statement alias mapping ----------

def test_income_statement_alias_camel_to_snake() -> None:
    raw_row = {
        "date": "2025-09-27",
        "period": "FY",
        "calendarYear": "2025",
        "symbol": "AAPL",
        "revenue": 416161000000,
        "netIncome": 112010000000,
        "eps": 7.49,
        "epsDiluted": 7.46,
        "grossProfit": 195201000000,
        "fillingDate": "2025-10-31",
    }
    q = FinanceIncomeStatementFetcher.transform_query({"symbol": "AAPL"})
    data = FinanceIncomeStatementFetcher.transform_data(q, [raw_row])
    row = data[0]
    assert row.period_ending.isoformat() == "2025-09-27"
    assert row.fiscal_period == "FY"
    assert row.fiscal_year == 2025
    assert row.revenue == 416161000000
    assert row.consolidated_net_income == 112010000000
    assert row.basic_earnings_per_share == 7.49
    assert row.gross_profit == 195201000000
    assert row.filing_date.isoformat() == "2025-10-31"


# ---------- config registration ----------

def test_config_registers_convexvalue_source() -> None:
    assert "convexvalue" in DEFAULT_PRIORITIES
    assert DEFAULT_PRIORITIES["convexvalue"] == 100


def test_config_convexvalue_api_key_expands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CV_API_KEY", "expanded-key")
    cfg = get_source_config("convexvalue")
    assert cfg.enabled
    assert cfg.api_key == "expanded-key"


# ---------- chain aextract_data returns contract_count ----------

async def test_chain_aextract_returns_records_and_total(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CV_API_KEY", "k")
    # Build non-empty call/put rows so _flatten_chain actually emits records
    # (all-None rows are treated as illiquid and skipped).
    fields_idx = {name: i for i, name in enumerate(cv.CHAIN_FIELDS)}
    call_row = [None] * len(cv.CHAIN_FIELDS)
    put_row = [None] * len(cv.CHAIN_FIELDS)
    for row, contract_type in ((call_row, "call"), (put_row, "put")):
        row[fields_idx["expiration_date"]] = "2026-07-17"
        row[fields_idx["strike_price"]] = 500.0
        row[fields_idx["contract_type"]] = contract_type
        row[fields_idx["ticker"]] = f"O:SPY260717{contract_type[0].upper()}00500000"

    fake_raw = {
        "symbol": "SPY",
        "chain": [{
            "expiration": "2026-07-17",
            "strikes": [[500.0, call_row, put_row]],
        }],
        "contract_count": 2,
    }

    async def fake_chains(symbol: str) -> dict[str, Any]:
        return fake_raw

    monkeypatch.setattr(cv, "fetch_chains", fake_chains)
    q = FinanceOptionsChainFetcher.transform_query({"symbol": "SPY"})
    data = await FinanceOptionsChainFetcher.aextract_data(q, None)
    assert data["contract_count"] == 2
    assert len(data["records"]) == 2  # one call + one put
    assert {r["option_type"] for r in data["records"]} == {"call", "put"}


# ---------- insider trading server-side filters pass through ----------

async def test_insider_trading_passes_transaction_type_and_after(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_fmp(endpoint: str, **params: Any) -> list[dict[str, Any]]:
        captured["endpoint"] = endpoint
        captured.update(params)
        return [{"symbol": "AAPL", "filingDate": "2025-01-01"}]

    monkeypatch.setattr(cv, "fetch_fmp", fake_fmp)
    from openbb_finance.models.insider_trading import FinanceInsiderTradingFetcher
    q = FinanceInsiderTradingFetcher.transform_query({
        "symbol": "AAPL", "transaction_type": "P-Purchase", "after": "2025-01-01", "limit": 10,
    })
    await FinanceInsiderTradingFetcher.aextract_data(q, None)
    assert captured["transactionType"] == "P-Purchase"
    assert captured["after"] == "2025-01-01"


# ---------- CLI helpers: _filter_sort_limit ----------

def test_filter_sort_limit_truncates_and_reports_meta() -> None:
    pytest.importorskip("openbb_agent_cli")
    from openbb_agent_cli.cli import _filter_sort_limit
    records = [{"oi": 100}, {"oi": 50}, {"oi": 200}, {"oi": None}]
    out, meta = _filter_sort_limit(records, sort_by="oi", sort_dir="desc", limit=2)
    assert [r["oi"] for r in out] == [200, 100]
    assert meta["returned"] == 2
    assert meta["filtered"] == 4  # None sorted last, still counted pre-limit
    assert meta["truncated"] is True
    assert meta["sort_by"] == "oi"
