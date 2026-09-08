"""Schwab Trader API data source, via the local schwab-api HTTP service.

openbb_finance never holds Schwab credentials: the schwab-api service
(services/schwab-api, default http://127.0.0.1:8010) is the single owner of
tokens and proxies Schwab REST JSON untouched. This source speaks plain HTTP
to it and is enabled only when ``sources.schwab.base_url`` expands to a
non-empty value — the default placeholder ``${SCHWAB_API_BASE_URL}`` collapses
to "" without the env var, so CI/foreign environments disable the source at
zero cost and routing falls back to tdx/tickflow.

Behaviour notes verified against the live service (2026-09, see
services/schwab-api/README.md quality assessment):
- pricehistory caps a single response at 40,000 candles and silently drops
  the OLDEST bars beyond that (the newest side is kept); long windows are
  paged backward by moving ``end`` just before the earliest kept bar.
- Quotes for index symbols need ``indicative=true`` and the ``$``-prefixed
  symbol form (``$SPX``/``$COMPX``/``$DJI``; the legacy ``$SPX.X`` is dead).
- ``errors.invalidSymbols`` rides along in a 200 response; consumers must
  check it.
- The service answers 503 when its token is missing/unauthenticated.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from openbb_finance.config import SourceConfig
from openbb_finance.sources.base import DataType, Market, PriceQuery, SourceError, normalize_interval

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")

# interval -> service param (the service whitelists exactly these values).
_SUPPORTED_INTERVALS: frozenset[str] = frozenset({"1m", "5m", "10m", "15m", "30m", "1d", "1w", "1M"})

# Schwab caps one pricehistory response at 40k candles (dropping the oldest
# side); pagination keeps going until a short page or this page budget.
_SCHWAB_CANDLE_CAP = 40_000
_MAX_PAGES = 10
_MS_PER_DAY = 86_400_000

# Per-page request span (calendar days) for backward pagination. A full page
# must stay well under the 40k candle cap (worst case: extended 1m bars at
# ~970/day), because wide sub-windows degrade server-side to tiny short
# responses — live-verified: a ~52-day 1m sub-window returned 337 bars, which
# a naive "short page = done" loop misreads as "window covered".
_PAGE_SPAN_DAYS: dict[str, int] = {
    "1m": 30,
    "5m": 90,
    "10m": 180,
    "15m": 180,
    "30m": 365,
}
_PAGE_SPAN_DEFAULT_DAYS = 3650

# US index symbols only verified against these; anything else ($NDX/$VIX, ...)
# fails with invalidSymbols -> SourceError -> tdx fallback, which is safe.
_INDEX_SYMBOL_MAP: dict[str, str] = {
    "SPX": "$SPX",
    "DJI": "$DJI",
    "COMPX": "$COMPX",
    "IXIC": "$COMPX",
}


class SchwabSource:
    name = "schwab"

    def __init__(self, config: SourceConfig) -> None:
        self.base_url = (config.base_url or "").rstrip("/")
        self.api_key = (config.api_key or "").strip() or None
        # The schwab-api endpoint is mandatory configuration; without it the
        # source is off (mirrors the finnhub "needs api key" gating).
        self.enabled = config.enabled and bool(self.base_url)

    def supports(self, market: Market, data_type: DataType, **kwargs: Any) -> bool:
        del kwargs
        return market == "us" and data_type in {"price", "fundamental", "search"}

    # ---- price ------------------------------------------------------------

    async def fetch_price(self, query: PriceQuery) -> list[dict[str, Any]]:
        interval = normalize_interval(query.interval)
        if interval not in _SUPPORTED_INTERVALS:
            # e.g. 60m/1h: raise so the router falls through to tdx instead of
            # surfacing a service 422.
            raise SourceError(f"Schwab source does not support interval {query.interval!r}")
        params: dict[str, Any] = {"symbol": _map_symbol(query.symbol), "interval": interval}
        # Always explicit: Schwab's own default includes pre/post-market bars
        # for minute intervals, so an omitted flag would silently change
        # semantics versus the documented extended=False default.
        params["extended"] = "true" if query.extended else "false"
        # `adjusted` is intentionally ignored: Schwab daily+ bars are split-
        # adjusted by default and it offers no QFQ/HFQ equivalent.
        # Window bounds as epoch-ms cursors in the ET calendar day: bars are
        # dated by their America/New_York date, so the window edges must be
        # anchored to ET midnight (not bare-date UTC midnights, which both
        # collapse to the same instant for start_date == end_date and reject
        # with "endDate is before startDate").
        start_ms = _et_date_to_ms(query.start_date) if query.start_date else None
        end_ms = _et_date_to_ms(query.end_date + timedelta(days=1)) - 1 if query.end_date else None
        intraday = interval.endswith("m")
        candles = await self._fetch_candles(params, interval=interval, start_ms=start_ms, end_ms=end_ms)
        rows = [_candle_to_row(candle, query.symbol, intraday=intraday) for candle in candles]
        # Schwab may pull in tail bars from before the requested start; clip
        # the window so callers see exactly the requested date range.
        if query.start_date:
            rows = [row for row in rows if _bar_date(row) >= query.start_date]
        if query.end_date:
            rows = [row for row in rows if _bar_date(row) <= query.end_date]
        return rows

    async def _fetch_candles(
        self,
        params: dict[str, Any],
        *,
        interval: str,
        start_ms: int | None,
        end_ms: int | None,
    ) -> list[dict[str, Any]]:
        """Collect candles for the window, paging backward across the 40k cap.

        Schwab keeps the newest 40,000 candles of a window and drops the
        oldest side, so page 1 covers [earliest_kept .. end]. Each further
        page moves ``end`` one millisecond before the earliest kept bar —
        endDate is inclusive, so the exact boundary bar would come back
        twice — and bounds the request span (``_PAGE_SPAN_DAYS``): wide
        sub-windows degrade server-side to tiny short responses (live-
        verified), which a naive "short page = window covered" loop would
        misread, silently losing the older history. Pages concatenate
        oldest-first; when the page budget is exhausted the newest side is
        kept (matching Schwab's own truncation bias) and we log a warning.
        """
        span_ms = _PAGE_SPAN_DAYS.get(interval, _PAGE_SPAN_DEFAULT_DAYS) * _MS_PER_DAY
        cursor_end_ms = end_ms
        if cursor_end_ms is None and start_ms is not None:
            # Explicit start without end: anchor the cursor at "now" so the
            # request always carries an explicit window (Schwab's default
            # period would otherwise cap it to the most recent days).
            cursor_end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        collected: list[dict[str, Any]] = []
        seen: set[Any] = set()
        for _ in range(_MAX_PAGES):
            page_params = dict(params)
            if cursor_end_ms is not None:
                page_params["end"] = _ms_to_iso(cursor_end_ms)
                floor_ms = cursor_end_ms - span_ms if start_ms is None else max(start_ms, cursor_end_ms - span_ms)
                page_params["start"] = _ms_to_iso(floor_ms)
            payload = await self._get("/api/v1/equity/price/historical", page_params)
            candles = [c for c in (payload.get("candles") or []) if isinstance(c, dict)]
            if not candles:
                break
            fresh = [c for c in candles if c.get("datetime") not in seen]
            if not fresh:
                # The server re-served only bars we already have (e.g. the
                # depth horizon sits inside this window): the cursor cannot
                # advance any further.
                break
            collected = fresh + collected
            seen.update(c.get("datetime") for c in fresh)
            earliest_ms = int(candles[0].get("datetime") or 0)
            covered = earliest_ms <= start_ms if start_ms is not None else len(candles) < _SCHWAB_CANDLE_CAP
            if covered:
                break
            cursor_end_ms = earliest_ms - 1
        else:
            logger.warning(
                "Schwab price history hit the %d-page limit for %s; keeping the newest side only",
                _MAX_PAGES,
                params.get("symbol"),
            )
        # oldest-first order: `fresh` pages were prepended during collection.
        return collected

    # ---- quote ------------------------------------------------------------

    async def fetch_quote(self, symbol: str) -> dict[str, Any]:
        requested = symbol.strip().upper()
        api_symbol = _map_symbol(requested)
        params: dict[str, Any] = {"symbols": api_symbol}
        if api_symbol.startswith("$"):
            params["indicative"] = "true"
        payload = await self._get("/api/v1/equity/price/quote", params)
        if not isinstance(payload, dict):
            raise SourceError(f"Schwab quote response is not an object for {requested}")
        invalid = (payload.get("errors") or {}).get("invalidSymbols")
        if invalid:
            raise SourceError(f"Schwab reported invalid symbols: {invalid}")
        entry = payload.get(api_symbol)
        if not isinstance(entry, dict):
            raise SourceError(f"Schwab quote response missing entry for {api_symbol}")
        return _quote_to_row(entry, requested)

    # ---- search / fundamental ----------------------------------------------

    async def fetch_equity_search(self, query: str, is_symbol: bool | None = None) -> list[dict[str, Any]]:
        text = (query or "").strip()
        # Schwab instruments search is US-only; skip CJK queries outright.
        if not text or not text.isascii():
            return []
        projection = "symbol-search" if is_symbol else "desc-search"
        payload = await self._get("/api/v1/equity/search", {"symbol": text, "projection": projection})
        instruments = payload.get("instruments") if isinstance(payload, dict) else None
        rows: list[dict[str, Any]] = []
        for item in instruments or []:
            if not isinstance(item, dict):
                continue
            asset_type = str(item.get("assetType") or "")
            if asset_type != "EQUITY":
                continue
            rows.append(
                {
                    "symbol": str(item.get("symbol") or "").strip().upper(),
                    "name": item.get("description"),
                    "exchange": item.get("exchange"),
                    "type": asset_type,
                    "source": "schwab",
                }
            )
        return rows

    async def fetch_fundamental(self, symbol: str) -> dict[str, Any]:
        requested = symbol.strip().upper()
        payload = await self._get("/api/v1/equity/fundamental", {"symbol": requested})
        entry = payload.get(requested) if isinstance(payload, dict) else None
        if not isinstance(entry, dict):
            raise SourceError(f"Schwab fundamental response missing entry for {requested}")
        fundamental = entry.get("fundamental") if isinstance(entry.get("fundamental"), dict) else {}
        return {"symbol": requested, "source": "schwab", **fundamental}

    # ---- options ------------------------------------------------------------

    async def fetch_options_chain(
        self,
        symbol: str,
        *,
        dte: int,
        strike_count: int,
        range_: str | None = None,
        strategy: str | None = None,
    ) -> dict[str, Any]:
        """Filtered option chain as flat records.

        dte/strike_count are mandatory: unfiltered big chains (SPY) overflow
        Schwab's gateway buffer (the service surfaces that as 502).

        Returns {"records": [...], "contract_count": N} where contract_count
        is Schwab's server-reported total.
        """
        if not dte or not strike_count:
            raise SourceError("Schwab option chain requires dte and strike_count filters")
        params: dict[str, Any] = {
            "symbol": symbol.strip().upper(),
            "dte": int(dte),
            "strike_count": int(strike_count),
        }
        if range_:
            params["range"] = range_
        if strategy:
            params["strategy"] = strategy
        raw = await self._get("/api/v1/options/chains", params)
        from openbb_finance.models.schwab_options_chain import flatten_schwab_chain

        records = flatten_schwab_chain(raw, query_symbol=symbol.strip().upper())
        contract_count = raw.get("numberOfContracts") if isinstance(raw, dict) else None
        return {"records": records, "contract_count": int(contract_count or len(records))}

    # ---- plumbing ------------------------------------------------------------

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        if not self.base_url:
            raise SourceError("Schwab API base URL is not configured")
        cleaned = {key: value for key, value in params.items() if value is not None}
        headers = {"X-API-Key": self.api_key} if self.api_key else None
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(f"{self.base_url}{path}", params=cleaned, headers=headers)
        except httpx.RequestError as exc:
            raise SourceError(f"schwab-api unreachable at {self.base_url}: {exc}") from exc
        if response.status_code == 503:
            raise SourceError(
                "schwab-api returned 503 (not authenticated or not started); "
                "open the service UI to authorize, then retry"
            )
        if response.is_error:
            raise SourceError(f"schwab-api request failed: {response.status_code}: {response.text[:200]}")
        return response.json()


def _et_date_to_ms(day: date) -> int:
    """ET-midnight of *day* as epoch milliseconds."""
    return int(datetime(day.year, day.month, day.day, tzinfo=_ET).timestamp() * 1000)


def _ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _bar_date(row: dict[str, Any]) -> date:
    value = row["date"]
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _map_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    return _INDEX_SYMBOL_MAP.get(value, value)


def _candle_to_row(candle: dict[str, Any], symbol: str, *, intraday: bool) -> dict[str, Any]:
    ts_ms = candle.get("datetime")
    if intraday:
        # Minute bars are exposed as America/New_York naive datetimes, aligned
        # with the tdx market-local-time convention.
        bar = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).astimezone(_ET).replace(tzinfo=None)
    else:
        bar = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).astimezone(_ET).date()
    return {
        "symbol": symbol,
        "date": bar,
        "open": _optional_float(candle.get("open")),
        "high": _optional_float(candle.get("high")),
        "low": _optional_float(candle.get("low")),
        "close": _optional_float(candle.get("close")),
        "volume": _optional_float(candle.get("volume")),
        "source": "schwab",
    }


def _quote_to_row(entry: dict[str, Any], requested_symbol: str) -> dict[str, Any]:
    quote = entry.get("quote") if isinstance(entry.get("quote"), dict) else {}
    return {
        "symbol": requested_symbol,
        "name": entry.get("description"),
        "last_price": _optional_float(quote.get("lastPrice")),
        "bid": _optional_float(quote.get("bidPrice")),
        "bid_size": _optional_float(quote.get("bidSize")),
        "ask": _optional_float(quote.get("askPrice")),
        "ask_size": _optional_float(quote.get("askSize")),
        "open": _optional_float(quote.get("openPrice")),
        "high": _optional_float(quote.get("highPrice")),
        "low": _optional_float(quote.get("lowPrice")),
        "prev_close": _optional_float(quote.get("closePrice")),
        "volume": _optional_float(quote.get("totalVolume")),
        "change": _optional_float(quote.get("netChange")),
        "change_percent": _optional_float(quote.get("netPercentChange")),
        "year_high": _optional_float(quote.get("52WeekHigh")),
        "year_low": _optional_float(quote.get("52WeekLow")),
        "source": "schwab",
    }


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
