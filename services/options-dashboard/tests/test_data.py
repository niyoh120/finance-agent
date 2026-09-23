"""Focused tests for the data bridge (async, throttle, 429 cooldown, chain aggregate).

Uses real async helpers against in-process fakes to avoid network. Verifies:
- run_async works from a thread without a running loop.
- run_async works from inside a running loop (worker-thread path).
- throttle enforces minimum interval.
- 429 sets a cool-down that subsequent acquire() calls observe.
- ConvexValueError with HTTP 429 maps to RateLimitedError and arms cooldown.
- ConvexValueError with other status maps to DataUnavailableError.
- Chain aggregate: Schwab field priority, CV fills None + out-of-window rows,
  single-source degradation, both-fail error, no-source error, local dte clip,
  and the Schwab 60s success cache (second call skips upstream).
"""

from __future__ import annotations

import asyncio
import time
from datetime import date
from typing import Any
from unittest.mock import patch

import options_dashboard.data as data_mod
import pytest
from options_dashboard.data import (
    DataUnavailableError,
    RateLimitedError,
    _Throttle,
    fetch_option_chain_sync,
    run_async,
    throttle,
)


@pytest.fixture(autouse=True)
def _reset_shared_chain_state():
    """Keep the process-wide chain cache and throttle out of test ordering."""
    data_mod._schwab_chain_cache.clear()
    throttle._cooldown_until = 0.0
    throttle._failure_count = 0
    yield
    data_mod._schwab_chain_cache.clear()
    throttle._cooldown_until = 0.0
    throttle._failure_count = 0


# ---------- run_async ----------


def test_run_async_runs_simple_coroutine() -> None:
    async def coro() -> int:
        await asyncio.sleep(0)
        return 42

    # Patch throttle.acquire to a no-op so this test doesn't sleep.
    with patch.object(data_mod.throttle, "acquire", lambda: None):
        assert run_async(coro()) == 42


def test_run_async_inside_running_loop_uses_worker_thread() -> None:
    """When a loop is already running, run_async must not deadlock.

    Runs an outer event loop on the main thread (via asyncio.run) that itself
    calls run_async; the inner call is dispatched to the worker thread.
    """

    async def inner() -> str:
        await asyncio.sleep(0)
        return "inner-ok"

    async def outer() -> str:
        # Inside a running loop here -> worker-thread path.
        return run_async(inner())

    with patch.object(data_mod.throttle, "acquire", lambda: None):
        result = asyncio.run(outer())
    assert result == "inner-ok"


# ---------- throttle ----------


@pytest.mark.parametrize("unused", range(3))
def test_throttle_enforces_min_interval(monkeypatch: pytest.MonkeyPatch, unused: int) -> None:
    """Independent throttle instances must enforce the configured interval.

    Runs three times (parametrize) to catch flaky interaction with the shared
    module-level instance. Uses a fresh _Throttle each time.
    """
    monkeypatch.setattr(data_mod, "_MIN_INTERVAL_SECONDS", 0.05)
    th = _Throttle()
    start = time.monotonic()
    th.acquire()
    th.acquire()
    th.acquire()
    elapsed = time.monotonic() - start
    # 3 requests with 0.05s spacing -> at least ~0.10s total (2 gaps).
    assert elapsed >= 0.09


def test_throttle_cooldown_after_429() -> None:
    th = _Throttle()
    th._cooldown_until = 0.0  # ensure clean
    th.notify_429()
    with pytest.raises(RateLimitedError):
        th.acquire()


def test_throttle_stats_reports_cooldown() -> None:
    th = _Throttle()
    th._cooldown_until = 0.0
    th._failure_count = 0
    th.notify_429()
    stats = th.stats()
    assert stats["failure_count"] == 1
    assert stats["cooldown_remaining"] > 0


# ---------- error mapping ----------


def test_fetch_fmp_maps_429_to_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    from openbb_finance.sources import convexvalue as cv

    async def fake_fmp(endpoint: str, **params: Any) -> Any:
        raise cv.ConvexValueError("ConvexValue fmp/stable/earnings returned HTTP 429")

    # Bypass throttle.acquire so cooldown is only set by the 429 path.
    monkeypatch.setattr(data_mod.throttle, "acquire", lambda: None)
    monkeypatch.setattr(cv, "fetch_fmp", fake_fmp)

    # Reset shared throttle cooldown so this test is independent.
    throttle._cooldown_until = 0.0
    throttle._failure_count = 0

    with pytest.raises(RateLimitedError):
        data_mod.fetch_fmp_sync("earnings", symbol="AAPL")
    # The 429 path must have armed the shared throttle.
    assert throttle.stats()["cooldown_remaining"] > 0


def test_fetch_fmp_maps_404_to_data_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from openbb_finance.sources import convexvalue as cv

    async def fake_fmp(endpoint: str, **params: Any) -> Any:
        raise cv.ConvexValueError("ConvexValue fmp/stable/badendpoint returned HTTP 404: not found")

    monkeypatch.setattr(data_mod.throttle, "acquire", lambda: None)
    monkeypatch.setattr(cv, "fetch_fmp", fake_fmp)
    throttle._cooldown_until = 0.0

    with pytest.raises(DataUnavailableError):
        data_mod.fetch_fmp_sync("badendpoint", symbol="AAPL")


# ---------- semantic FMP wrappers ----------


def test_fetch_profile_sync_unwraps_first_row(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_mod.throttle, "acquire", lambda: None)
    monkeypatch.setattr(
        data_mod,
        "fetch_fmp_sync",
        lambda endpoint, **params: [{"symbol": "AAPL", "lastDividend": 1.0, "price": 200.0}],
    )
    profile = data_mod.fetch_profile_sync("AAPL")
    assert profile["symbol"] == "AAPL"
    assert profile["lastDividend"] == 1.0


def test_fetch_profile_sync_raises_on_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_mod.throttle, "acquire", lambda: None)
    monkeypatch.setattr(data_mod, "fetch_fmp_sync", lambda endpoint, **params: [])
    with pytest.raises(DataUnavailableError):
        data_mod.fetch_profile_sync("NOPE")


def test_fetch_treasury_rates_sync_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake(endpoint, **params):
        captured["endpoint"] = endpoint
        captured.update(params)
        return [{"date": "2026-07-10", "year1": 4.06}]

    monkeypatch.setattr(data_mod.throttle, "acquire", lambda: None)
    monkeypatch.setattr(data_mod, "fetch_fmp_sync", fake)
    rows = data_mod.fetch_treasury_rates_sync(limit=5)
    assert rows[0]["year1"] == 4.06


def test_fetch_equity_eod_sync_handles_nested_historical(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_mod.throttle, "acquire", lambda: None)
    monkeypatch.setattr(
        data_mod,
        "fetch_fmp_sync",
        lambda endpoint, **params: {"historical": [{"date": "2026-07-10", "close": 316.0}]},
    )
    rows = data_mod.fetch_equity_eod_sync("AAPL", "2026-07-10", "2026-07-10")
    assert rows[0]["close"] == 316.0


def test_fetch_equity_eod_sync_raises_on_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_mod.throttle, "acquire", lambda: None)
    monkeypatch.setattr(data_mod, "fetch_fmp_sync", lambda endpoint, **params: {"historical": []})
    with pytest.raises(DataUnavailableError):
        data_mod.fetch_equity_eod_sync("NOPE", "2026-07-10", "2026-07-10")


def test_fetch_equity_quote_sync_unwraps_row(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_mod.throttle, "acquire", lambda: None)
    monkeypatch.setattr(
        data_mod,
        "_run_or_classify",
        lambda coro_factory: [{"symbol": "AAPL", "last_price": 201.5}],
    )
    quote = data_mod.fetch_equity_quote_sync("AAPL")
    assert quote["last_price"] == 201.5


def test_fetch_equity_quote_sync_raises_on_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_mod.throttle, "acquire", lambda: None)
    monkeypatch.setattr(data_mod, "_run_or_classify", lambda coro_factory: [])
    with pytest.raises(DataUnavailableError):
        data_mod.fetch_equity_quote_sync("NOPE")


# ---------- option chain aggregate (Schwab + ConvexValue) ----------


class _FakeSchwabSource:
    """Stands in for the registry's schwab source; counts upstream calls."""

    name = "schwab"
    enabled = True

    def __init__(self, records: list[dict[str, Any]] | None = None, error: Exception | None = None) -> None:
        self.records = records or []
        self.error = error
        self.calls = 0

    async def fetch_options_chain(self, symbol: str, *, dte: int, strike_count: int, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        self.last_kwargs = {"symbol": symbol, "dte": dte, "strike_count": strike_count, **kwargs}
        if self.error is not None:
            raise self.error
        return {"records": list(self.records), "contract_count": len(self.records)}


class _FakeRegistry:
    def __init__(self, schwab: _FakeSchwabSource | None) -> None:
        self._schwab = schwab

    def get(self, name: str) -> Any:
        return self._schwab if name == "schwab" else None


def _schwab_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "contract_symbol": "AAPL260918C00100000",
        "expiration": date(2026, 9, 18),
        "strike": 100.0,
        "option_type": "call",
        "dte": 66,
        "implied_volatility": 0.25,
        "delta": 0.6,
        "theoretical_price": 7.5,
        "open_interest": None,
        "underlying_price": 101.0,
    }
    row.update(overrides)
    return row


def _cv_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "contract_symbol": "O:AAPL260918C00100000",
        "expiration": date(2026, 9, 18),
        "strike": 100.0,
        "option_type": "call",
        "dte": 66,
        "implied_volatility": None,
        "delta": 0.55,
        "theoretical_price": 5.0,
        "open_interest": 1000,
        "underlying_price": 100.5,
    }
    row.update(overrides)
    return row


def _patch_sources(
    monkeypatch: pytest.MonkeyPatch,
    *,
    schwab: _FakeSchwabSource | None,
    cv_records: list[dict[str, Any]] | Exception | None = None,
    cv_enabled: bool = True,
    patch_cv_fetch: bool = True,
) -> None:
    """Wire the aggregate's upstream seams to in-memory fakes.

    ``patch_cv_fetch=False`` keeps the real ``_fetch_chain_cv`` (used by the
    429-mapping test); the CV enabled flag still decides participation.
    """
    import openbb_finance.registry as registry_mod

    monkeypatch.setattr(registry_mod, "build_default_registry", lambda: _FakeRegistry(schwab))
    monkeypatch.setattr(data_mod, "_cv_api_key", lambda: "test-key" if cv_enabled else "")
    if patch_cv_fetch:

        async def fake_cv(symbol: str) -> list[dict[str, Any]]:
            if isinstance(cv_records, Exception):
                raise cv_records
            return list(cv_records or [])

        monkeypatch.setattr(data_mod, "_fetch_chain_cv", fake_cv)


def test_chain_aggregate_schwab_priority_and_cv_fill(monkeypatch: pytest.MonkeyPatch) -> None:
    """In-window: Schwab fields win, CV fills nulls; CV-only rows survive."""
    schwab = _FakeSchwabSource([_schwab_row()])
    cv_side = [
        _cv_row(),
        _cv_row(
            contract_symbol="O:AAPL270319P00050000",
            expiration=date(2027, 3, 19),
            strike=50.0,
            option_type="put",
            dte=380,
            theoretical_price=1.25,
            open_interest=42,
        ),
    ]
    _patch_sources(monkeypatch, schwab=schwab, cv_records=cv_side)

    records = fetch_option_chain_sync("aapl")

    assert len(records) == 2
    by_key = {(r["expiration"], r["strike"], r["option_type"]): r for r in records}
    in_window = by_key[(date(2026, 9, 18), 100.0, "call")]
    # Schwab wins populated fields (pricing convention + bare OCC symbol)...
    assert in_window["theoretical_price"] == 7.5
    assert in_window["theoretical_price_source"] == "schwab"
    assert in_window["contract_symbol"] == "AAPL260918C00100000"
    # ...CV fills the field Schwab left null...
    assert in_window["open_interest"] == 1000
    assert in_window["open_interest_source"] == "convexvalue"
    # ...and the out-of-window contract comes out as an all-CV row.
    out_window = by_key[(date(2027, 3, 19), 50.0, "put")]
    assert out_window["theoretical_price"] == 1.25
    assert out_window["theoretical_price_source"] == "convexvalue"


def test_chain_degrades_to_cv_when_schwab_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from openbb_finance.sources.base import SourceError

    schwab = _FakeSchwabSource(error=SourceError("schwab-api unreachable"))
    _patch_sources(monkeypatch, schwab=schwab, cv_records=[_cv_row()])

    records = fetch_option_chain_sync("AAPL")

    assert len(records) == 1
    assert records[0]["theoretical_price"] == 5.0
    assert records[0]["theoretical_price_source"] == "convexvalue"


def test_chain_cv_429_notifies_throttle_and_schwab_supplies(monkeypatch: pytest.MonkeyPatch) -> None:
    """A CV 429 inside the aggregate arms the cool-down and degrades to Schwab."""
    from openbb_finance.models import equity_options_chain as chain_mod
    from openbb_finance.sources import convexvalue as cv

    schwab = _FakeSchwabSource([_schwab_row()])
    _patch_sources(monkeypatch, schwab=schwab, cv_enabled=True, patch_cv_fetch=False)
    # Keep the real _fetch_chain_cv; only neutralize spacing (no real sleep).
    monkeypatch.setattr(data_mod.throttle, "acquire", lambda: None)

    async def fake_aextract(query: Any, credentials: Any) -> Any:
        raise cv.ConvexValueError("ConvexValue /chains returned HTTP 429")

    monkeypatch.setattr(chain_mod.FinanceOptionsChainFetcher, "aextract_data", fake_aextract)

    records = fetch_option_chain_sync("AAPL")

    assert schwab.calls == 1
    assert len(records) == 1
    assert records[0]["theoretical_price_source"] == "schwab"
    stats = throttle.stats()
    assert stats["cooldown_remaining"] > 0
    assert stats["failure_count"] == 1


def test_chain_both_sources_fail_raises_with_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    from openbb_finance.sources.base import SourceError

    schwab = _FakeSchwabSource(error=SourceError("503"))
    _patch_sources(monkeypatch, schwab=schwab, cv_records=DataUnavailableError("cv down"))

    with pytest.raises(DataUnavailableError) as excinfo:
        fetch_option_chain_sync("AAPL")
    message = str(excinfo.value)
    assert "schwab" in message and "convexvalue" in message
    assert "无" in message  # succeeded list empty


def test_chain_no_sources_enabled_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_sources(monkeypatch, schwab=None, cv_enabled=False)

    with pytest.raises(DataUnavailableError) as excinfo:
        fetch_option_chain_sync("AAPL")
    assert "SCHWAB_API_BASE_URL" in str(excinfo.value)


def test_chain_schwab_dte_clipped_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    """Schwab's server-side dte filter is loose; the window is enforced locally."""
    schwab = _FakeSchwabSource(
        [
            _schwab_row(),
            _schwab_row(
                contract_symbol="AAPL270617C00100000",
                expiration=date(2027, 6, 17),
                strike=100.0,
                dte=400,
                theoretical_price=9.9,
            ),
        ]
    )
    _patch_sources(monkeypatch, schwab=schwab, cv_enabled=False)

    records = fetch_option_chain_sync("AAPL")

    assert [r["dte"] for r in records] == [66]
    assert schwab.last_kwargs["dte"] == data_mod._SCHWAB_CHAIN_DTE_DAYS
    assert schwab.last_kwargs["strike_count"] == data_mod._SCHWAB_CHAIN_STRIKE_COUNT


def test_chain_schwab_ttl_cache_skips_second_upstream_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """The 60s success cache serves the second call without re-hitting Schwab."""
    schwab = _FakeSchwabSource([_schwab_row()])
    _patch_sources(monkeypatch, schwab=schwab, cv_records=[_cv_row()])

    first = fetch_option_chain_sync("AAPL")
    second = fetch_option_chain_sync("AAPL")

    assert schwab.calls == 1
    # Both fakes share one (expiration, strike, option_type) key -> one merged row.
    assert len(first) == len(second) == 1
    assert first == second
