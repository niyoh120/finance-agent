"""Async-to-sync bridge, throttling and ConvexValue/FMP access.

Streamlit pages call the sync functions in this module; they forward to the
async helpers in :mod:`openbb_finance` via a dedicated worker thread. The
option chain is a Schwab + ConvexValue aggregate (see ``_aggregate_chain``);
the other wrappers talk to ConvexValue directly. A process-wide throttle
enforces a minimum interval between ConvexValue requests and a cool-down after
HTTP 429 so all sessions share the same rate-limit budget. ``st.cache_data``
layers (applied in the calling page) provide TTL caching across reruns; the
only cache in this module is the Schwab chain success cache (60s TTL) that
keeps the Schwab request budget flat while the 5s auto-refresh fragment
re-hits ConvexValue for fresh valuations.
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

# --------------------------------------------------------------------------- #
# Option-chain aggregation constants
# --------------------------------------------------------------------------- #
#
# dte/strike_count are mandatory Schwab query filters: unfiltered big chains
# (SPY) overflow the schwab-api gateway buffer (the service surfaces that as
# 502). The declared window also mirrors the openbb-agent-cli aggregate.
_SCHWAB_CHAIN_DTE_DAYS = 365
_SCHWAB_CHAIN_STRIKE_COUNT = 50
# Process-wide TTL for successful Schwab chain fetches. The 5s auto-refresh
# fragment clears only the page-level st.cache_data, so this cache keeps the
# Schwab budget at ~1 req/min while ConvexValue valuations stay fresh.
_SCHWAB_CHAIN_TTL_SECONDS = 60.0


class _SuccessfulTtlCache:
    """Per-key TTL cache that only stores successful results.

    The lock is deliberately scoped to dict reads/writes and never held across
    an await: every async call in this module runs on the single worker loop,
    so a lock held across an upstream await would block the loop and deadlock
    concurrent chain requests. Concurrent misses may both fetch; the page-level
    ``st.cache_data`` dedupes the common case, and failures are never stored so
    the next caller retries upstream.
    """

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, Any]] = {}

    def peek(self, key: str) -> Any | None:
        """Return the cached value for *key* when fresh, else ``None``."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and time.monotonic() < entry[0]:
                return entry[1]
            return None

    def store(self, key: str, value: Any) -> None:
        with self._lock:
            self._entries[key] = (time.monotonic() + self._ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


# Single process-wide instance (same rationale as ``throttle`` below).
_schwab_chain_cache = _SuccessfulTtlCache(_SCHWAB_CHAIN_TTL_SECONDS)


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


# --------------------------------------------------------------------------- #
# Option chain: Schwab + ConvexValue aggregation
# --------------------------------------------------------------------------- #


def _cv_api_key() -> str:
    """Resolve the ConvexValue API key without raising (env first, then config).

    Same precedence as ``convexvalue._get_api_key``; used only to decide
    whether the CV side of the options-chain aggregation participates.
    """
    import os

    key = os.environ.get("CV_API_KEY", "").strip()
    if not key:
        from openbb_finance.config import get_source_config

        key = (get_source_config("convexvalue").api_key or "").strip()
    return key


async def _fetch_chain_cv(symbol: str) -> list[dict[str, Any]]:
    """Full ConvexValue chain — the pre-aggregation behavior, kept as the
    single-line rollback point for ``fetch_option_chain_sync``.

    Runs on the worker loop and is awaited directly: ``run_async`` from inside
    that loop would self-deadlock, so ``throttle.acquire`` moved in here (same
    spacing/cool-down contract as the old ``run_async`` path). A 429 arms the
    cool-down then propagates: ``aggregate_records`` swallows it and degrades
    to the other source.
    """
    from openbb_finance.models.equity_options_chain import (
        FinanceOptionsChainFetcher,
    )
    from openbb_finance.sources import convexvalue as cv

    throttle.acquire()
    try:
        q = FinanceOptionsChainFetcher.transform_query({"symbol": symbol})
        data = await FinanceOptionsChainFetcher.aextract_data(q, None)
    except cv.ConvexValueError as exc:
        if "429" in str(exc):
            throttle.notify_429()
            raise RateLimitedError(str(exc)) from exc
        raise DataUnavailableError(str(exc)) from exc
    records = data.get("records", []) if isinstance(data, dict) else data
    if not records:
        raise DataUnavailableError(f"ConvexValue chain empty for {symbol}")
    return records


async def _fetch_chain_schwab(source: Any, symbol: str) -> list[dict[str, Any]]:
    """Schwab chain within the declared window, via the 60s success cache.

    Schwab's server-side dte filter is loose (contracts beyond the declared
    window still come back), so the window is enforced locally after
    flattening; strike_count is honored server-side.
    """
    cached = _schwab_chain_cache.peek(symbol)
    if cached is not None:
        return cached
    data = await source.fetch_options_chain(symbol, dte=_SCHWAB_CHAIN_DTE_DAYS, strike_count=_SCHWAB_CHAIN_STRIKE_COUNT)
    records = [r for r in data["records"] if r.get("dte") is not None and r["dte"] <= _SCHWAB_CHAIN_DTE_DAYS]
    _schwab_chain_cache.store(symbol, records)
    return records


async def _aggregate_chain(symbol: str) -> list[dict[str, Any]]:
    """Merge the Schwab and ConvexValue chains field-by-field.

    Source order IS the priority (schwab first), mirroring the openbb-agent-cli
    aggregate: in-window contracts take every populated field from Schwab
    (unified pricing/greeks conventions, trusted quote timestamps); CV fills
    fields Schwab leaves null and contributes out-of-window contracts
    (far-dated / deep-OTM) on its own. Any single source failure is swallowed
    by ``aggregate_records`` and degrades to the other source alone.
    ``*_source`` annotations are kept so the page can attribute values and
    hint when a source is missing.
    """
    from types import SimpleNamespace

    from openbb_finance.aggregator import aggregate_records
    from openbb_finance.registry import build_default_registry

    schwab = build_default_registry().get("schwab")
    cv_source = SimpleNamespace(name="convexvalue", enabled=bool(_cv_api_key()))
    participants = [s for s in (schwab, cv_source) if s is not None and s.enabled]
    if not participants:
        raise DataUnavailableError("期权链无可用数据源：未配置 SCHWAB_API_BASE_URL，且 ConvexValue API key 缺失。")

    state: dict[str, Any] = {"used": []}

    async def fetch(source: Any) -> list[dict[str, Any]]:
        name = getattr(source, "name", "")
        records = await _fetch_chain_schwab(source, symbol) if name == "schwab" else await _fetch_chain_cv(symbol)
        # Only reached on success; failures propagate to aggregate_records,
        # which logs, swallows, and degrades to the remaining sources.
        state["used"].append(name)
        return records

    merged = await aggregate_records(participants, fetch, key_fields=("expiration", "strike", "option_type"))
    if not merged:
        raise DataUnavailableError(
            f"期权链无数据（启用源：{[s.name for s in participants]}，"
            f"实际供数：{state['used'] or '无'}）；请稍后重试或检查上游服务。"
        )
    return merged


def fetch_option_chain_sync(symbol: str) -> list[dict[str, Any]]:
    """Return flattened option-chain records for *symbol* (Schwab+CV aggregate).

    Records keep the aggregator's ``*_source`` field annotations. Submitted
    directly to the worker (bypassing ``run_async``'s throttle acquire): the
    only throttled upstream in the aggregate is ConvexValue, gated inside
    :func:`_fetch_chain_cv`, so a CV 429 cool-down degrades to Schwab instead
    of failing the whole chain.
    """
    return _worker.submit(_aggregate_chain(str(symbol).strip().upper()))


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
