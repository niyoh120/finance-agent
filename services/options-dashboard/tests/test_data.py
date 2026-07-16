"""Focused tests for the data bridge (async, throttle, 429 cooldown).

Uses real async helpers against in-process fakes to avoid network. Verifies:
- run_async works from a thread without a running loop.
- run_async works from inside a running loop (worker-thread path).
- throttle enforces minimum interval.
- 429 sets a cool-down that subsequent acquire() calls observe.
- ConvexValueError with HTTP 429 maps to RateLimitedError and arms cooldown.
- ConvexValueError with other status maps to DataUnavailableError.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import patch

import options_dashboard.data as data_mod
import pytest
from options_dashboard.data import (
    DataUnavailableError,
    RateLimitedError,
    _Throttle,
    run_async,
    throttle,
)

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
        raise cv.ConvexValueError(
            "ConvexValue fmp/stable/badendpoint returned HTTP 404: not found"
        )

    monkeypatch.setattr(data_mod.throttle, "acquire", lambda: None)
    monkeypatch.setattr(cv, "fetch_fmp", fake_fmp)
    throttle._cooldown_until = 0.0

    with pytest.raises(DataUnavailableError):
        data_mod.fetch_fmp_sync("badendpoint", symbol="AAPL")


# ---------- semantic FMP wrappers ----------

def test_fetch_profile_sync_unwraps_first_row(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_mod.throttle, "acquire", lambda: None)
    monkeypatch.setattr(
        data_mod, "fetch_fmp_sync",
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
        data_mod, "fetch_fmp_sync",
        lambda endpoint, **params: {"historical": [{"date": "2026-07-10", "close": 316.0}]},
    )
    rows = data_mod.fetch_equity_eod_sync("AAPL", "2026-07-10", "2026-07-10")
    assert rows[0]["close"] == 316.0


def test_fetch_equity_eod_sync_raises_on_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_mod.throttle, "acquire", lambda: None)
    monkeypatch.setattr(
        data_mod, "fetch_fmp_sync", lambda endpoint, **params: {"historical": []}
    )
    with pytest.raises(DataUnavailableError):
        data_mod.fetch_equity_eod_sync("NOPE", "2026-07-10", "2026-07-10")


def test_fetch_equity_quote_sync_unwraps_row(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_mod.throttle, "acquire", lambda: None)
    monkeypatch.setattr(
        data_mod, "_run_or_classify",
        lambda coro_factory: [{"symbol": "AAPL", "last_price": 201.5}],
    )
    quote = data_mod.fetch_equity_quote_sync("AAPL")
    assert quote["last_price"] == 201.5


def test_fetch_equity_quote_sync_raises_on_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_mod.throttle, "acquire", lambda: None)
    monkeypatch.setattr(data_mod, "_run_or_classify", lambda coro_factory: [])
    with pytest.raises(DataUnavailableError):
        data_mod.fetch_equity_quote_sync("NOPE")
