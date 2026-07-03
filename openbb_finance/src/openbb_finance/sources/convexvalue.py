"""ConvexValue (cvforge Research Plan) REST API data source.

Reverse-engineered API documented in docs/ConvexValue REST API 数据接口文档.md.
All endpoints are POST JSON with Bearer token auth. Base URL:
https://tap.convexvalue.com/api/data

Two data libraries under one subscription:
- Massive options: /chains, /screen, /query, /mas/aggs, /mas/open-close
- FMP (210 endpoints): /fmp/stable/<endpoint>

API key is read from the CV_API_KEY env var (configured as ${CV_API_KEY} in
openbb_finance.toml / DEFAULT_CONFIG). Models call these helpers directly
rather than routing through the multi-source registry, because ConvexValue
provides data unavailable from the other sources (tdx/tickflow/akshare/etc.).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

# ponytail: module-level constants — CV field set is fixed by the backend.
# Discovered via MCP list_chain_fields (the authoritative 42-field enum).
OPTIONS_SNAPSHOTS_FIELDS: tuple[str, ...] = (
    "underlying_ticker", "ticker", "break_even_price", "implied_volatility",
    "open_interest", "fair_market_value", "day_change", "day_change_percent",
    "day_close", "day_high", "day_last_updated", "day_low", "day_open",
    "day_previous_close", "day_volume", "day_vwap", "contract_type",
    "exercise_style", "expiration_date", "shares_per_contract", "strike_price",
    "delta", "gamma", "theta", "vega", "ask", "ask_size", "bid", "bid_size",
    "quote_last_updated", "midpoint", "quote_timeframe", "trade_conditions",
    "trade_exchange", "trade_price", "trade_sip_timestamp", "trade_size",
    "trade_timeframe", "underlying_change_to_break_even",
    "underlying_last_updated", "underlying_price", "underlying_symbol",
    "underlying_timeframe", "fetched_at",
)

# Curated 32-field subset for /chains (CV hard limit is 32 params). Covers the
# openbb OptionsChainsData standard fields plus the high-value CV extensions
# (fair_market_value, break_even_price, day_vwap, exercise_style). The
# remaining 10 fields (trade_conditions, quote_timeframe, *_timeframe, etc.)
# are low-value system/metadata fields.
CHAIN_FIELDS: tuple[str, ...] = (
    # contract reference
    "expiration_date", "strike_price", "contract_type", "ticker",
    "exercise_style", "shares_per_contract",
    # greeks + IV
    "delta", "gamma", "theta", "vega", "implied_volatility",
    # pricing
    "bid", "bid_size", "ask", "ask_size", "midpoint",
    "fair_market_value", "break_even_price",
    # open interest + volume
    "open_interest", "day_volume",
    # day stats
    "day_open", "day_high", "day_low", "day_close",
    "day_previous_close", "day_change", "day_change_percent", "day_vwap",
    # underlying
    "underlying_symbol", "underlying_price", "underlying_change_to_break_even",
    # trade
    "trade_price",
)
assert len(CHAIN_FIELDS) == 32, f"CHAIN_FIELDS must be 32, got {len(CHAIN_FIELDS)}"

_BASE_URL = "https://tap.convexvalue.com/api/data"
_USER_AGENT = "cv-preview-node/0.1"
_TIMEOUT = 30.0
# 502 retry backoff: CV/FMP upstream intermittently returns 502 HTML error pages.
# Retry twice with increasing delay; other 5xx codes use the same schedule.
_RETRY_BACKOFF = (1.0, 3.0)


class ConvexValueError(RuntimeError):
    """Raised for non-recoverable ConvexValue API failures (4xx after retries)."""


def _get_api_key() -> str:
    # Prefer the live env var (the common path when openbb_finance.toml uses
    # ${CV_API_KEY}), then fall back to whatever was loaded into the source
    # config (supports a literal key written directly in TOML).
    key = os.environ.get("CV_API_KEY", "").strip()
    if not key:
        from openbb_finance.config import get_source_config

        key = (get_source_config("convexvalue").api_key or "").strip()
    if not key:
        raise ConvexValueError(
            "ConvexValue API key is not set. "
            "Configure sources.convexvalue.api_key in openbb_finance.toml "
            "or export CV_API_KEY."
        )
    return key


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_api_key()}",
        "Content-Type": "application/json",
        "User-Agent": _USER_AGENT,
    }


async def _post(endpoint: str, body: dict[str, Any] | None = None) -> Any:
    """POST to a ConvexValue endpoint and return the parsed JSON response.

    Retries on 5xx (notably FMP upstream 502 HTML pages) using a fixed backoff.
    Raises ConvexValueError on 4xx (client errors are not retryable) or when
    the body cannot be parsed as JSON (e.g. an HTML error page after retries).
    """
    url = f"{_BASE_URL}/{endpoint.lstrip('/')}"
    payload = body or {}
    last_error: Exception | None = None
    for attempt, delay in enumerate([0.0, *_RETRY_BACKOFF]):
        if delay:
            await asyncio.sleep(delay)
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                response = await client.post(url, headers=_headers(), json=payload)
        except httpx.RequestError as exc:
            last_error = ConvexValueError(
                f"ConvexValue {endpoint} request failed: {exc}"
            )
            continue
        if response.status_code >= 500:
            last_error = ConvexValueError(
                f"ConvexValue {endpoint} returned HTTP {response.status_code}"
            )
            continue
        if response.status_code >= 400:
            raise ConvexValueError(
                f"ConvexValue {endpoint} returned HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ConvexValueError(
                f"ConvexValue {endpoint} returned non-JSON response: "
                f"{response.text[:200]}"
            ) from exc
    raise last_error or ConvexValueError(f"ConvexValue {endpoint} failed after retries")


# ---- endpoint-specific helpers -------------------------------------------

async def fetch_chains(symbol: str) -> dict[str, Any]:
    """Return the full option chain for *symbol* using CHAIN_FIELDS."""
    return await _post("chains", {"symbol": symbol.upper(), "params": list(CHAIN_FIELDS)})


async def fetch_screen(
    *,
    columns: list[str],
    filters: list[dict[str, Any]],
    sort: list[dict[str, Any]] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Run a cross-symbol option screen with AND filters."""
    body: dict[str, Any] = {"columns": columns, "filters": filters, "limit": limit}
    if sort:
        body["sort"] = sort
    return await _post("screen", body)


async def fetch_query(sql: str, max_rows: int | None = None) -> dict[str, Any]:
    """Run a read-only SELECT/WITH SQL against the options_snapshots DuckDB table."""
    body: dict[str, Any] = {"sql": sql}
    if max_rows is not None:
        body["max_rows"] = max_rows
    return await _post("query", body)


async def fetch_option_aggregates(
    *,
    ticker: str,
    multiplier: int,
    timespan: str,
    date_from: str,
    date_to: str,
    adjusted: bool = True,
    sort: str = "asc",
    limit: int = 5000,
) -> dict[str, Any]:
    """Aggregated OHLCV bars for a single option contract (Massive Aggregates)."""
    return await _post(
        "mas/aggs",
        {
            "ticker": ticker,
            "multiplier": multiplier,
            "timespan": timespan,
            "from": date_from,
            "to": date_to,
            "adjusted": adjusted,
            "sort": sort,
            "limit": limit,
        },
    )


async def fetch_option_open_close(ticker: str, date: str) -> dict[str, Any]:
    """Single-day OHLCV for an option contract."""
    return await _post("mas/open-close", {"ticker": ticker, "date": date})


async def fetch_fmp(endpoint: str, **params: Any) -> Any:
    """Call a /fmp/stable/<endpoint> with the given query params.

    Array values are comma-joined per FMP convention; falsy values are dropped.
    """
    body = {
        key: value
        for key, value in params.items()
        if value is not None and value != ""
    }
    return await _post(f"fmp/stable/{endpoint.lstrip('/')}", body)
