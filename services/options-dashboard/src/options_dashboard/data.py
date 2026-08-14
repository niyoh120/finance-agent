"""Async-to-sync bridge, throttling and ConvexValue/FMP access.

Streamlit pages call the sync functions in this module; they forward to the
existing async helpers in :mod:`openbb_finance.sources.convexvalue` via a
dedicated worker thread. A process-wide throttle enforces a minimum interval
between upstream requests and a cool-down after HTTP 429 so all sessions share
the same rate-limit budget. ``st.cache_data`` layers (applied in the calling
page) provide TTL caching across reruns; this module stays cache-free so unit
tests can exercise throttling without Streamlit.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Process-wide minimum interval between upstream requests (seconds).
# ConvexValue Research Plan has per-minute limits; a conservative 0.2s floor
# keeps bursts under ~300/min regardless of how many sessions are active.
_MIN_INTERVAL_SECONDS = 0.2
# Cool-down applied after an HTTP 429. During cool-down, requests raise
# RateLimitedError so the page can show a recoverable message and keep the
# already-edited strategy intact.
_COOLDOWN_SECONDS = 30.0


class RateLimitedError(RuntimeError):
    """Raised when the global throttle is in 429 cool-down."""


class DataUnavailableError(RuntimeError):
    """Raised when an upstream call returns no usable data (4xx/5xx/empty)."""


class _Throttle:
    """Process-wide request throttle shared by all Streamlit sessions.

    Two guards: a minimum interval between successive requests, and a cool-down
    window set after a 429. Both are advisory; per-request correctness is still
    the caller's responsibility (e.g. serializing earnings analysis).

    Locked because Streamlit runs one script per browser session in parallel.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_request_at: float = 0.0
        self._cooldown_until: float = 0.0
        self._failure_count: int = 0

    def acquire(self) -> None:
        """Block until the minimum interval has elapsed; raise during cool-down.

        During a 429 cool-down we do NOT sleep until it expires — that would
        freeze the UI thread for up to ``_COOLDOWN_SECONDS``. Instead we raise
        immediately so the page can surface a recoverable message and keep the
        user's already-edited strategy intact.
        """
        with self._lock:
            now = time.monotonic()
            if self._cooldown_until > now:
                raise RateLimitedError("Upstream rate limit (429) cool-down active; retry later.")
            elapsed = now - self._last_request_at
            wait = max(0.0, _MIN_INTERVAL_SECONDS - elapsed)
            # Reserve this slot atomically so concurrent threads queue behind it.
            self._last_request_at = now + wait
        if wait > 0:
            time.sleep(wait)

    def notify_429(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._cooldown_until = time.monotonic() + _COOLDOWN_SECONDS

    def stats(self) -> dict[str, float | int]:
        with self._lock:
            now = time.monotonic()
            return {
                "cooldown_remaining": max(0.0, self._cooldown_until - now),
                "failure_count": self._failure_count,
                "seconds_since_last": now - self._last_request_at if self._last_request_at else -1.0,
            }


# Single process-wide instance. Module-level on purpose: every Streamlit
# thread and every test in this process must share the same budget.
throttle = _Throttle()


# --------------------------------------------------------------------------- #
# async -> sync bridge
# --------------------------------------------------------------------------- #


def run_async(coro: Awaitable[T]) -> T:
    """Run *coro* to completion from sync code on the process-wide worker loop.

    Always dispatches to the single dedicated worker thread that owns a
    persistent event loop — never ``asyncio.run``. A fresh loop per call would
    make loop-bound resources (e.g. a shared ``httpx.AsyncClient`` connection
    pool in the finance sources) unusable across calls; one long-lived loop
    lets every call reuse the same pool and keeps ConvexValue requests serial
    across all sessions, which is what the Research Plan rate limit wants.
    """
    throttle.acquire()
    return _worker.submit(coro)


async def _strip_awaitable(coro: Awaitable[T]) -> T:
    # Awaitables from regular `async def` functions are already coroutines;
    # awaiting them uniformly keeps the type narrow.
    return await coro  # type: ignore[misc]


class _WorkerThread:
    """Single-thread async executor for the rare "loop already running" case.

    A dedicated thread runs its own event loop forever; ``submit`` schedules a
    coroutine and blocks the caller until the result is ready. Bounded by
    design: one worker for the whole process keeps ConvexValue requests serial
    across all sessions, which is exactly what the Research Plan rate limit
    wants.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def submit(self, coro: Awaitable[T]) -> T:
        self._ensure_started()
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(_strip_awaitable(coro), self._loop)  # type: ignore[arg-type]
        return future.result()

    def _ensure_started(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            ready = threading.Event()

            def _runner() -> None:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                ready.set()
                self._loop.run_forever()

            self._thread = threading.Thread(target=_runner, name="od-async-worker", daemon=True)
            self._thread.start()
            ready.wait(timeout=5.0)
            if self._loop is None:
                raise RuntimeError("Failed to start async worker thread")


_worker = _WorkerThread()


# --------------------------------------------------------------------------- #
# ConvexValue / FMP sync wrappers
# --------------------------------------------------------------------------- #
#
# Each wrapper centralizes:
#   - throttle (via run_async)
#   - 429 detection -> throttle.notify_429 -> RateLimitedError
#   - empty / error -> DataUnavailableError
# Pages still apply st.cache_data on top for TTL behavior.


def _run_or_classify(coro: Callable[[], Awaitable[Any]]) -> Any:
    from openbb_finance.sources import convexvalue as cv

    try:
        return run_async(coro())
    except cv.ConvexValueError as exc:
        text = str(exc)
        if "HTTP 429" in text or "429" in text:
            throttle.notify_429()
            raise RateLimitedError(text) from exc
        raise DataUnavailableError(text) from exc


def fetch_option_chain_sync(symbol: str) -> list[dict[str, Any]]:
    """Return flattened option-chain records for *symbol* (CV /chains)."""
    from openbb_finance.models.equity_options_chain import (
        FinanceOptionsChainFetcher,
    )

    q = FinanceOptionsChainFetcher.transform_query({"symbol": symbol})
    data = _run_or_classify(lambda: FinanceOptionsChainFetcher.aextract_data(q, None))
    records = data.get("records", []) if isinstance(data, dict) else data
    if not records:
        raise DataUnavailableError(f"ConvexValue chain empty for {symbol}")
    return records


def fetch_equity_quote_sync(symbol: str) -> dict[str, Any]:
    """Return the live equity quote (last_price, bid, ask, ...) via openbb finance.

    Routes through the finance provider's EquityQuote fetcher, which tries
    tdx / tickflow under the hood. Used by the strategy page to auto-fill the
    underlying spot without asking the user to type it.
    """
    from openbb_finance.models.equity_quote import FinanceEquityQuoteFetcher

    q = FinanceEquityQuoteFetcher.transform_query({"symbol": symbol})
    rows = _run_or_classify(lambda: FinanceEquityQuoteFetcher.aextract_data(q, None))
    if isinstance(rows, list) and rows:
        # Return a plain dict; callers pick the fields they need.
        row = rows[0]
        return dict(row) if hasattr(row, "model_dump") else dict(row)
    raise DataUnavailableError(f"Equity quote empty for {symbol}")


def fetch_option_daily_sync(contract: str, date: str) -> dict[str, Any]:
    """Single-day OHLCV for an option contract (CV /mas/open-close)."""
    from openbb_finance.models.equity_options_daily import (
        FinanceOptionDailyFetcher,
    )

    q = FinanceOptionDailyFetcher.transform_query({"symbol": contract, "date": date})
    rows = _run_or_classify(lambda: FinanceOptionDailyFetcher.aextract_data(q, None))
    if isinstance(rows, list) and rows:
        return dict(rows[0])
    raise DataUnavailableError(f"ConvexValue option daily empty for {contract}@{date}")


def fetch_fmp_sync(endpoint: str, **params: Any) -> Any:
    """Call a ConvexValue-proxied FMP /stable/<endpoint> synchronously."""
    data = _run_or_classify(lambda: _cv_fetch_fmp(endpoint, **params))
    if data is None:
        raise DataUnavailableError(f"FMP {endpoint} returned no data")
    return data


async def _cv_fetch_fmp(endpoint: str, **params: Any) -> Any:
    from openbb_finance.sources import convexvalue as cv

    return await cv.fetch_fmp(endpoint, **params)


# --------------------------------------------------------------------------- #
# Semantic FMP helpers (thin wrappers around fetch_fmp_sync)
# --------------------------------------------------------------------------- #


def fetch_profile_sync(symbol: str) -> dict[str, Any]:
    """FMP company profile (lastDividend, price, sector, etc.)."""
    rows = fetch_fmp_sync("profile", symbol=symbol)
    if isinstance(rows, list) and rows:
        return dict(rows[0])
    raise DataUnavailableError(f"FMP profile empty for {symbol}")


def fetch_earnings_sync(symbol: str, limit: int = 8) -> list[dict[str, Any]]:
    """FMP historical + upcoming earnings dates and EPS estimates/actuals."""
    rows = fetch_fmp_sync("earnings", symbol=symbol, limit=limit)
    if not isinstance(rows, list):
        raise DataUnavailableError(f"FMP earnings unexpected shape for {symbol}")
    return [dict(r) for r in rows]


def fetch_treasury_rates_sync(limit: int = 30) -> list[dict[str, Any]]:
    """FMP daily Treasury yield curve (most recent ``limit`` sessions)."""
    rows = fetch_fmp_sync("treasury-rates", limit=limit)
    if not isinstance(rows, list):
        raise DataUnavailableError("FMP treasury-rates unexpected shape")
    return [dict(r) for r in rows]


def fetch_equity_eod_sync(symbol: str, date_from: str, date_to: str, *, adjusted: bool = True) -> list[dict[str, Any]]:
    """FMP historical end-of-day prices for an underlying.

    ``adjusted`` selects dividend/split-adjusted prices when true (used for
    realized-volatility and return series), and the ``full`` (unadjusted)
    endpoint otherwise (used when matching raw option underlying prints).
    """
    endpoint = "historical-price-eod/dividend-adjusted" if adjusted else "historical-price-eod/full"
    payload = fetch_fmp_sync(endpoint, symbol=symbol, **{"from": date_from, "to": date_to})
    rows = payload.get("historical") if isinstance(payload, dict) else payload
    if not rows:
        raise DataUnavailableError(f"FMP {endpoint} empty for {symbol} [{date_from}..{date_to}]")
    return [dict(r) for r in rows]
