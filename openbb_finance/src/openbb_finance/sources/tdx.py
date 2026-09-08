"""TDX data source consuming the local tdx-api HTTP service (services/tdx-api).

The service owns all TDX protocol complexity (handshake, binary framing, host
failover, QFQ adjustment); this source is a plain HTTP consumer of its
``/api/v1`` JSON API. Running dependencies are HTTP-only: no ``easy_tdx``
import, no sockets, no adjustment math on this side.

Gating mirrors SchwabSource: ``sources.tdx.base_url`` must expand to a
non-empty http(s) root (``${TDX_API_BASE_URL}`` collapses to "" when unset, so
the source is disabled at zero cost and routing falls back to the remaining
sources). An optional ``sources.tdx.api_key`` is sent as ``X-API-Key``.

Resource budgets (documented in openbb_finance/README.md):
- per-request: 5s connect / 35s read (the service itself budgets 30s per
  request, so a read timeout here means the service overrun is real);
- per fetch_* call: one short-lived ``httpx.AsyncClient`` shared by every
  request of that call (pagination pages and cross-market searches), bounded
  by a 60s wall-clock budget covering queueing and all pages;
- the service performs upstream retries; each HTTP request is sent exactly
  once from here.
"""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any, AsyncIterator

import httpx

from openbb_finance.config import SourceConfig
from openbb_finance.sources.base import (
    DataType,
    Market,
    PriceQuery,
    SourceError,
    infer_market,
    normalize_interval,
)
from openbb_finance.sources.symbols import (
    FUTURES_MONTH_LETTERS,
    FUTURES_MONTH_NUMBERS,
    INTL_FUTURES_EXCHANGES,
    SGE_SPOT_MAP,
    SH_SUFFIXES,
    SZ_SUFFIXES,
    cn_exchange,
    cn_plain_symbol,
    futures_exchange,
    futures_plain_code,
    split_symbol,
    to_openbb_symbol,
)

logger = logging.getLogger(__name__)

#: TCP connect timeout per HTTP request.
CONNECT_TIMEOUT_SECONDS = 5.0
#: Per-request read timeout; must cover the service-side 30s request budget.
READ_TIMEOUT_SECONDS = 35.0
#: Wall-clock budget for one public fetch call (queueing + all pages/markets).
FETCH_BUDGET_SECONDS = 60.0

#: Service API root appended to the configured base URL.
API_PREFIX = "/api/v1"

#: Intervals the service accepts; user-facing aliases resolve through
#: normalize_interval ("60" -> "60m") plus the explicit "1h" -> "60m" map.
SERVICE_INTERVALS: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "60m": "60m",
    "1h": "60m",
    "1d": "1d",
    "1w": "1w",
    "1M": "1M",
}
#: Minute-grained service intervals. Kept explicit because the shared
#: is_intraday_interval() helper lower-cases input and misclassifies "1M".
MINUTE_INTERVALS = frozenset({"1m", "5m", "15m", "30m", "60m"})

#: Kline pagination: single-page cap, page budget, and the default newest-window
#: size when the caller gives no start_date (TDX convention).
KLINE_PAGE_LIMIT = 1000
KLINE_MAX_PAGES = 20
DEFAULT_KLINE_COUNT = 700

#: Equity search targets all five stock markets. Futures search covers the
#: directory-enabled futures markets: the CFFEX directory capability is
#: disabled in the service (upstream directory missing), so CFFEX search
#: yields [] and the fetcher keeps its existing akshare fallback.
EQUITY_SEARCH_MARKETS = ("cn_sh", "cn_sz", "hk", "hk_gem", "us")
FUTURES_SEARCH_MARKETS = ("shfe", "dce", "czce", "gfex", "comex", "nymex", "cbot", "sge")
SEARCH_PAGE_LIMIT = 1000
SEARCH_MAX_PAGES = 10
SEARCH_MAX_RESULTS = 10_000
SEARCH_CONCURRENCY = 3

#: Search-result normalization labels (user-facing exchange short codes).
EQUITY_MARKET_EXCHANGE = {"cn_sh": "XSHG", "cn_sz": "XSHE", "hk": "HK", "hk_gem": "HKGEM", "us": "US"}
EQUITY_MARKET_SYMBOL_SUFFIX = {"cn_sh": ".XSHG", "cn_sz": ".XSHE", "hk": ".HK", "hk_gem": ".HK"}

#: User symbol -> tdx-api market routing for indices. The value is the
#: service-native code: the service normalizes these aliases internally
#: (markets.py INTL_INDEX_CODES/HK_INDEX_CODES) and quote rows echo the
#: native code back from the wire, so the consumer must send and match the
#: native form to keep quote row matching exact.
INTL_INDEX_SERVICE_CODES: dict[str, str] = {
    "SPX": "A_SPX",
    "DJI": "A_DJI",
    "IXIC": "A_IXIC",
    "NDX": "A_NDX",
}
HK_INDEX_SERVICE_CODES: dict[str, str] = {
    "HSI": "HSI",
    "HSCEI": "HZ5014",
    "HSTECH": "HZ5017",
}

#: Exchange short code -> tdx-api market id.
FUTURES_SERVICE_MARKETS: dict[str, str] = {
    "SHFE": "shfe",
    "DCE": "dce",
    "CZCE": "czce",
    "CFFEX": "cffex",
    "GFEX": "gfex",
    "COMEX": "comex",
    "NYMEX": "nymex",
    "CBOT": "cbot",
    "SGE": "sge",
}
#: Domestic commodity main continuous suffix; CFFEX uses L0 (service README +
#: live test contract), international exchanges use 00W.
DOMESTIC_MAIN_CONTINUOUS_SUFFIX = "L8"
CFFEX_MAIN_CONTINUOUS_SUFFIX = "L0"
INTL_MAIN_CONTINUOUS_SUFFIX = "00W"

_EQUITY_SUFFIX_TO_MARKETS: dict[str, tuple[str, ...]] = {
    # Recognized equity suffixes narrow the search targets; HK covers both the
    # main board and GEM because the plain ".HK" suffix does not distinguish.
    **{suffix: ("cn_sh",) for suffix in SH_SUFFIXES},
    **{suffix: ("cn_sz",) for suffix in SZ_SUFFIXES},
    "HK": ("hk", "hk_gem"),
}


class TdxSource:
    """TDX market data source backed by the tdx-api HTTP service."""

    name = "tdx"

    def __init__(self, config: SourceConfig, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = _normalize_base_url(config.base_url)
        self.api_key = (config.api_key or "").strip() or None
        # The tdx-api endpoint is mandatory configuration; without it the
        # source is off (mirrors the schwab base_url gating).
        self.enabled = config.enabled and bool(self.base_url)
        self.timeout = READ_TIMEOUT_SECONDS
        self._transport = transport

    def supports(self, market: Market, data_type: DataType, **kwargs: Any) -> bool:
        del kwargs
        return market in {"cn", "hk", "us", "future"} and data_type in {"price", "search"}

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def fetch_price(self, query: PriceQuery) -> list[dict[str, Any]]:
        if query.start_date is not None and query.end_date is not None and query.start_date > query.end_date:
            raise SourceError(f"TDX invalid date range: start_date {query.start_date} > end_date {query.end_date}")
        service_market, service_code = _to_service_market(query.symbol, query.market, query.expiration)
        interval = _service_interval(query.interval)
        adjust = "qfq" if query.adjusted else "none"
        async with self._fetch_scope() as client:
            return await self._collect_klines(
                client,
                service_market=service_market,
                service_code=service_code,
                interval=interval,
                adjust=adjust,
                symbol=query.symbol,
                start_date=query.start_date,
                end_date=query.end_date,
            )

    async def fetch_quote(self, symbol: str, expiration: str | None = None) -> dict[str, Any]:
        service_market, service_code = _to_service_market(symbol, infer_market(symbol), expiration)
        async with self._fetch_scope() as client:
            data, meta = await self._get_envelope(
                client,
                "/quotes",
                {"market": service_market, "codes": service_code},
            )
        rows = _require_row_dicts(data, "quotes")
        row = _match_quote_row(rows, service_market, service_code, symbol)
        if _is_futures_like(symbol):
            return _normalize_futures_quote(row, symbol, meta)
        return _normalize_quote(row, symbol, meta)

    async def fetch_futures_search(self, query: str, is_symbol: bool | None = None) -> list[dict[str, Any]]:
        """Search futures/SGE instruments via the service directory pagination.

        The service exposes no native code search for these markets that also
        resolves user symbols like ``AU9999.SGE`` (the native SGE name is
        ``Au99.99``), so the client pages ``/instruments`` per market and
        matches code/name/symbol locally, keeping the auxiliary-continuous
        filtering. Strict completeness: any market failure or incomplete
        directory fails the whole search so routing falls back to akshare.
        """
        text = (query or "").strip().upper()
        if not text:
            return []
        async with self._fetch_scope() as client:
            rows = await self._search_markets(client, "/instruments", FUTURES_SEARCH_MARKETS, {})
        exchange_by_market = {service: exchange for exchange, service in FUTURES_SERVICE_MARKETS.items()}
        results: list[dict[str, Any]] = []
        for row in rows:
            market = row.get("market")
            exchange = exchange_by_market.get(market) if isinstance(market, str) else None
            code = str(row.get("code") or "").strip()
            if exchange is None or not code:
                raise SourceError(f"TDX futures directory returned an unrecognized row (market={market!r})")
            if not _is_queryable_futures_code(exchange, code):
                continue
            symbol, expiration = _futures_contract_symbol(exchange, code)
            name = str(row.get("name") or "").strip()
            if _futures_search_match(text, code.upper(), name.upper(), symbol.upper(), is_symbol):
                results.append(
                    {
                        "symbol": symbol,
                        "expiration": expiration,
                        "code": code,
                        "name": name,
                        "exchange": exchange,
                        "source": "tdx",
                    }
                )
        return _dedup_sorted(results, key=lambda item: (item["exchange"], item["code"]))

    async def fetch_equity_search(self, query: str, is_symbol: bool | None = None) -> list[dict[str, Any]]:
        """Keyword/code search across cn_sh/cn_sz/hk/hk_gem/us.

        Fully-qualified codes (six-digit CN codes, digit codes with an explicit
        ``.HK`` suffix) take the cheap ``/instruments/info`` fast path; every
        other query pages ``/instruments/search`` across the target markets
        with bounded concurrency. The service's EX search also matches the
        desc field, so results are re-filtered to the public code/name/symbol
        semantics. Strict completeness: any market failure or incomplete
        directory fails the whole search (all-or-nothing).
        """
        text = (query or "").strip()
        if not text:
            return []
        markets, term, info_candidates = _plan_equity_search(text)
        if not term:
            return []
        async with self._fetch_scope() as client:
            if info_candidates is not None:
                hits = await self._equity_info_lookup(client, info_candidates)
                if hits is not None:
                    rows = hits
                else:
                    # Exact-code miss: the full search over the narrowed
                    # markets keeps semantics identical to search-only.
                    rows = await self._search_markets(client, "/instruments/search", markets, {"query": term})
            else:
                rows = await self._search_markets(client, "/instruments/search", markets, {"query": term})
        results = [row for item in rows if (row := _finalize_equity_row(item, term, is_symbol)) is not None]
        return _dedup_sorted(results, key=lambda item: item["symbol"])

    # ------------------------------------------------------------------ #
    # Plumbing
    # ------------------------------------------------------------------ #

    @asynccontextmanager
    async def _fetch_scope(self) -> AsyncIterator[httpx.AsyncClient]:
        """One AsyncClient + one wall-clock budget per public fetch call."""
        _require_base_url(self.base_url)
        try:
            async with asyncio.timeout(FETCH_BUDGET_SECONDS):
                async with self._make_client() as client:
                    yield client
        except TimeoutError as exc:
            raise SourceError(f"TDX fetch exceeded the {FETCH_BUDGET_SECONDS:.0f}s budget") from exc

    def _make_client(self) -> httpx.AsyncClient:
        headers = {"X-API-Key": self.api_key} if self.api_key else None
        return httpx.AsyncClient(
            base_url=f"{self.base_url}{API_PREFIX}",
            timeout=httpx.Timeout(READ_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS),
            headers=headers,
            transport=self._transport,
        )

    async def _get_envelope(
        self, client: httpx.AsyncClient, path: str, params: dict[str, Any]
    ) -> tuple[Any, dict[str, Any]]:
        """GET one ``{"data", "meta"}`` envelope; every failure maps to SourceError."""
        cleaned = {key: value for key, value in params.items() if value is not None}
        try:
            response = await client.get(path, params=cleaned)
        except httpx.HTTPError as exc:
            # Never leak base_url/auth headers into messages; path + error class
            # are enough to triage.
            raise SourceError(f"TDX service request failed for {path}: {type(exc).__name__}") from exc
        return _parse_envelope(response, path)

    async def _collect_klines(
        self,
        client: httpx.AsyncClient,
        *,
        service_market: str,
        service_code: str,
        interval: str,
        adjust: str,
        symbol: str,
        start_date: date | None,
        end_date: date | None,
    ) -> list[dict[str, Any]]:
        """Page /klines backward from the newest window into history.

        - offset starts at 0 (newest) and follows the service's ``next_offset``.
        - With start_date: page until the oldest bar covers start_date or the
          service declares the history end (meta.complete); output is the
          inclusive [start_date, end_date] window.
        - Without start_date: keep at most the DEFAULT_KLINE_COUNT newest bars
          dated on or before end_date (end_date=None keeps the newest window).
        - Truncation is never returned as success: page-budget exhaustion, a
          stalled/regressed cursor, a non-advancing page, or an incomplete
          empty page raise SourceError so the router can fall back.
        """
        merged: list[dict[str, Any]] = []  # ascending; newer pages arrive first
        seen: set[date | datetime] = set()
        oldest_key: date | datetime | None = None
        cursor = 0

        for page_index in range(KLINE_MAX_PAGES):
            data, meta = await self._get_envelope(
                client,
                "/klines",
                {
                    "market": service_market,
                    "code": service_code,
                    "interval": interval,
                    "adjust": adjust,
                    "offset": cursor,
                    "limit": KLINE_PAGE_LIMIT,
                },
            )
            rows = _require_bar_rows(data)
            _validate_page_meta(meta, rows, cursor)
            complete = meta["complete"]

            if not rows:
                if complete is False:
                    raise SourceError("TDX kline pagination returned an empty page with an incomplete status")
                break  # explicit history end

            items = [_normalize_bar_row(row, symbol, interval) for row in rows]
            fresh = [item for item in items if item["date"] not in seen]
            if page_index > 0:
                page_min = min(item["date"] for item in fresh) if fresh else None
                if page_min is None or page_min >= oldest_key:
                    raise SourceError("TDX kline pagination did not advance toward older history")
            seen.update(item["date"] for item in fresh)
            merged = fresh + merged
            page_oldest = min(item["date"] for item in items)
            oldest_key = page_oldest if oldest_key is None else min(oldest_key, page_oldest)

            if complete:
                # Service-declared history end wins even when a next_offset
                # rides along on a full final page.
                break
            next_offset = meta["next_offset"]
            if next_offset is None or next_offset <= cursor:
                raise SourceError("TDX kline pagination cursor is missing or regressed")

            if start_date is not None:
                # Bars outside the window still drive coverage decisions.
                if _bar_date(oldest_key) <= start_date:
                    break
            else:
                in_window = sum(1 for item in merged if end_date is None or _bar_date(item["date"]) <= end_date)
                if in_window >= DEFAULT_KLINE_COUNT:
                    break
            cursor = next_offset
        else:
            raise SourceError(
                f"TDX kline pagination exhausted the {KLINE_MAX_PAGES}-page budget without covering the request"
            )

        return _finalize_kline_window(merged, start_date, end_date)

    async def _search_markets(
        self,
        client: httpx.AsyncClient,
        path: str,
        markets: tuple[str, ...],
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Fan out a directory query across markets with bounded concurrency.

        Strict completeness (all-or-nothing): any market failure, an incomplete
        directory, a stalled cursor, or an exhausted page/result/time budget
        raises SourceError and cancels the remaining markets, so the router can
        fall back cleanly instead of serving partial results.
        """
        semaphore = asyncio.Semaphore(SEARCH_CONCURRENCY)

        async def run(market: str) -> tuple[str, list[dict[str, Any]]]:
            async with semaphore:
                rows = await self._page_directory(client, path, {**params, "market": market}, market=market)
            return market, rows

        try:
            async with asyncio.TaskGroup() as task_group:
                tasks = [task_group.create_task(run(market)) for market in markets]
        except* SourceError as group:
            raise group.exceptions[0]

        # tasks keep the fixed market order; merge before per-market filters.
        merged: list[dict[str, Any]] = []
        for task in tasks:
            merged.extend(task.result()[1])
        if len(merged) > SEARCH_MAX_RESULTS:
            raise SourceError(f"TDX search exceeded the {SEARCH_MAX_RESULTS}-result budget")
        return merged

    async def _page_directory(
        self,
        client: httpx.AsyncClient,
        path: str,
        params: dict[str, Any],
        *,
        market: str,
    ) -> list[dict[str, Any]]:
        """Page a per-market list endpoint until the service declares completion."""
        items: list[dict[str, Any]] = []
        cursor = 0
        for _page in range(SEARCH_MAX_PAGES):
            data, meta = await self._get_envelope(
                client,
                path,
                {**params, "offset": cursor, "limit": SEARCH_PAGE_LIMIT},
            )
            rows = _require_row_dicts(data, f"{path} rows ({market})")
            _validate_page_meta(meta, rows, cursor)
            if meta.get("directory_complete") is False:
                raise SourceError(f"TDX directory for market {market} is incomplete")
            if not rows:
                if meta["complete"] is False:
                    raise SourceError(
                        f"TDX directory paging for market {market} returned an empty page with an incomplete status"
                    )
                break  # explicit end of the directory / matches
            items.extend(rows)
            if len(items) > SEARCH_MAX_RESULTS:
                raise SourceError(f"TDX search for market {market} exceeded the {SEARCH_MAX_RESULTS}-result budget")
            if meta["complete"]:
                break
            next_offset = meta["next_offset"]
            if next_offset is None or next_offset <= cursor:
                raise SourceError(f"TDX directory paging cursor for market {market} is missing or regressed")
            cursor = next_offset
        else:
            raise SourceError(f"TDX directory paging for market {market} exhausted the {SEARCH_MAX_PAGES}-page budget")
        return items

    async def _equity_info_lookup(
        self,
        client: httpx.AsyncClient,
        candidates: list[tuple[str, str]],
    ) -> list[dict[str, Any]] | None:
        """Resolve exact-code candidates via /instruments/info.

        Returns the first matching row (candidates are the same code across
        mutually exclusive markets), or None when every candidate misses;
        data=null is a normal no-match, not an error."""
        for market, code in candidates:
            data, _meta = await self._get_envelope(client, "/instruments/info", {"market": market, "code": code})
            if data is None:
                continue
            if not isinstance(data, dict):
                raise SourceError(f"TDX instrument info returned a malformed row for {market}/{code}")
            if data.get("market") != market or str(data.get("code") or "") != code:
                raise SourceError(f"TDX instrument info mismatched the requested {market}/{code}")
            return [data]
        return None


# ---------------------------------------------------------------------- #
# Envelope / error mapping
# ---------------------------------------------------------------------- #


def _parse_envelope(response: httpx.Response, path: str) -> tuple[Any, dict[str, Any]]:
    status = response.status_code
    if status == 401:
        raise SourceError(f"TDX service rejected credentials (401) for {path}")
    if response.is_error:
        raise SourceError(f"TDX service error ({status}) for {path}: {_error_context(response)}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise SourceError(f"TDX service returned invalid JSON for {path}") from exc
    if not isinstance(payload, dict):
        raise SourceError(f"TDX service response is not an object for {path}")
    # Defensive: a well-behaved service maps errors to HTTP status codes, but an
    # error envelope on 200 must still fail loudly instead of returning garbage.
    if isinstance(payload.get("error"), dict):
        error = payload["error"]
        raise SourceError(f"TDX service error for {path}: {error.get('code')}: {error.get('message')}")
    if "data" not in payload or not isinstance(payload.get("meta"), dict):
        raise SourceError(f"TDX service response missing data/meta for {path}")
    return payload["data"], payload["meta"]


def _error_context(response: httpx.Response) -> str:
    """Short non-sensitive failure context: error envelope code or HTTP detail."""
    try:
        payload = response.json()
    except ValueError:
        return f"http {response.status_code}"
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return f"{error.get('code')}: {error.get('message')}"
        detail = payload.get("detail")
        if isinstance(detail, str) and detail:
            return detail
    return f"http {response.status_code}"


def _require_row_dicts(data: Any, what: str) -> list[dict[str, Any]]:
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise SourceError(f"TDX service returned malformed {what} rows")
    return data


# ---------------------------------------------------------------------- #
# Market / symbol mapping (user symbol -> tdx-api (market, native code))
# ---------------------------------------------------------------------- #


def _normalize_base_url(value: str | None) -> str:
    """Trim whitespace/trailing slashes; scheme validity is enforced lazily."""
    return (value or "").strip().rstrip("/")


def _require_base_url(base_url: str) -> str:
    if not base_url:
        raise SourceError("TDX source has no base_url configured (set TDX_API_BASE_URL)")
    if not base_url.lower().startswith(("http://", "https://")):
        raise SourceError("TDX base_url must be an http(s) URL")
    return base_url


def _to_service_market(symbol: str, market_hint: Market, expiration: str | None = None) -> tuple[str, str]:
    """Map a user symbol to the tdx-api (market id, native code) pair."""
    if futures_exchange(symbol) is not None:
        return _to_futures_market(symbol, expiration)
    if market_hint == "cn":
        code = cn_plain_symbol(symbol)
        if code is None:
            raise SourceError(f"TDX only supports China A-share symbols: {symbol}")
        return ("cn_sh" if cn_exchange(symbol) == "sh" else "cn_sz"), code
    value = symbol.strip().upper()
    service_code = INTL_INDEX_SERVICE_CODES.get(value)
    if service_code is not None:
        return "intl_index", service_code
    service_code = HK_INDEX_SERVICE_CODES.get(value)
    if service_code is not None:
        return "hk_index", service_code
    code, suffix = _strip_equity_suffix(value)
    if market_hint == "hk":
        if not code.isdigit():
            raise SourceError(f"TDX invalid Hong Kong symbol: {symbol}")
        padded = code.zfill(5)
        return ("hk_gem" if padded.startswith("08") else "hk"), padded
    if market_hint == "us":
        if not code:
            raise SourceError(f"TDX invalid US symbol: {symbol}")
        # Internal dots (BRK.B) stay: only recognized exchange suffixes strip.
        return "us", code
    raise SourceError(f"TDX unsupported market: {market_hint}")


def _strip_equity_suffix(symbol: str) -> tuple[str, str | None]:
    """Split an equity symbol into (code, recognized suffix), keeping US dots.

    ``BRK.B`` stays whole (unknown suffix), ``700.HK`` -> ("700", "HK"),
    ``600519.SH`` -> ("600519", "SH").
    """
    code, suffix = split_symbol(symbol)
    if suffix in SH_SUFFIXES or suffix in SZ_SUFFIXES or suffix == "HK":
        return code, suffix
    return symbol, None


def _parse_expiration(expiration: str) -> tuple[str, int]:
    """Parse YYYY-MM into (YY string, month int), e.g. 2026-10 -> ("26", 10)."""
    match = re.fullmatch(r"(\d{4})-(\d{1,2})", expiration.strip())
    if match is None:
        raise SourceError(f"TDX invalid expiration (expected YYYY-MM): {expiration}")
    year, month = match.group(1), int(match.group(2))
    if not 1 <= month <= 12:
        raise SourceError(f"TDX invalid expiration month: {expiration}")
    return year[-2:], month


def _to_futures_market(symbol: str, expiration: str | None = None) -> tuple[str, str]:
    """Translate a user futures symbol + optional YYYY-MM expiration to tdx-api (market, code).

    Three code families:
    - SGE spot-deferred products use the fixed SGE_SPOT_MAP and ignore expiration.
    - Domestic exchanges: main continuous <CODE>L8 (CFFEX: <CODE>L0 per the
      service README/live contract), month contract <CODE><YYMM>.
    - International exchanges (COMEX/NYMEX/CBOT): main continuous <CODE>00W,
      month contract <CODE><YY><month-letter>.
    """
    exchange = futures_exchange(symbol)
    if exchange is None:
        raise SourceError(f"TDX invalid futures symbol: {symbol}")
    if exchange == "SGE":
        code = SGE_SPOT_MAP.get(f"{futures_plain_code(symbol)}.SGE")
        if code is None:
            raise SourceError(f"TDX unknown SGE product: {symbol}")
        return FUTURES_SERVICE_MARKETS[exchange], code
    code = futures_plain_code(symbol)
    if expiration is None:
        if exchange == "CFFEX":
            code = f"{code}{CFFEX_MAIN_CONTINUOUS_SUFFIX}"
        elif exchange in INTL_FUTURES_EXCHANGES:
            code = f"{code}{INTL_MAIN_CONTINUOUS_SUFFIX}"
        else:
            code = f"{code}{DOMESTIC_MAIN_CONTINUOUS_SUFFIX}"
    else:
        year, month = _parse_expiration(expiration)
        if exchange in INTL_FUTURES_EXCHANGES:
            code = f"{code}{year}{FUTURES_MONTH_LETTERS[month]}"
        else:
            code = f"{code}{year}{month:02d}"
    return FUTURES_SERVICE_MARKETS[exchange], code


def _futures_contract_symbol(exchange: str, code: str) -> tuple[str, str | None]:
    """Map a tdx-api native contract code to (user symbol, expiration YYYY-MM | None).

    Reverse of _to_futures_market: strips the L8/L0/00W main-continuous suffix
    or the YYMM / YY+month-letter suffix from the variety code and recomputes
    the user-facing symbol and expiration.
    """
    raw = code.strip()
    if exchange == "SGE":
        reverse = {tdx_code: user_symbol for user_symbol, tdx_code in SGE_SPOT_MAP.items()}
        user_symbol = reverse.get(raw)
        if user_symbol:
            return user_symbol, None
        return f"{raw.replace('.', '').upper()}.SGE", None
    upper = raw.upper()
    if exchange in INTL_FUTURES_EXCHANGES:
        if upper.endswith(INTL_MAIN_CONTINUOUS_SUFFIX):
            return f"{upper[: -len(INTL_MAIN_CONTINUOUS_SUFFIX)]}.{exchange}", None
        # Month contract: <VARIETY><YY><month-letter>, e.g. GC26Z.
        if len(upper) >= 4:
            for index in range(len(upper) - 3, 0, -1):
                suffix = upper[index:]
                if suffix[0:2].isdigit() and suffix[2] in FUTURES_MONTH_NUMBERS:
                    month = FUTURES_MONTH_NUMBERS[suffix[2]]
                    return f"{upper[:index]}.{exchange}", f"20{suffix[0:2]}-{month:02d}"
        return f"{upper}.{exchange}", None
    # Domestic: main continuous <CODE>L8 (CFFEX: <CODE>L0), month <CODE><YYMM>.
    main_suffix = CFFEX_MAIN_CONTINUOUS_SUFFIX if exchange == "CFFEX" else DOMESTIC_MAIN_CONTINUOUS_SUFFIX
    if upper.endswith(main_suffix):
        return f"{upper[: -len(main_suffix)]}.{exchange}", None
    if len(upper) >= 5:
        for index in range(len(upper) - 4, 0, -1):
            suffix = upper[index:]
            if suffix.isdigit() and len(suffix) == 4:
                return f"{upper[:index]}.{exchange}", f"20{suffix[0:2]}-{suffix[2:4]}"
    return f"{upper}.{exchange}", None


def _is_queryable_futures_code(exchange: str, code: str) -> bool:
    """Whether a tdx-api directory code maps back to a queryable user symbol.

    Main continuous (L8 / CFFEX L0 / 00W) and month contracts (YYMM /
    YY+month-letter) are queryable through _to_futures_market; auxiliary
    continuous codes (次连 L7, 加权 L9, 连续 00Y) are not, so they are filtered
    from search results.
    """
    upper = code.strip().upper()
    if exchange == "SGE":
        return True
    if exchange in INTL_FUTURES_EXCHANGES:
        if re.fullmatch(r"[A-Z0-9]+00[A-Z]", upper):
            return upper.endswith(INTL_MAIN_CONTINUOUS_SUFFIX)
        return True
    if re.fullmatch(r"[A-Z]+L\d", upper):
        expected = CFFEX_MAIN_CONTINUOUS_SUFFIX if exchange == "CFFEX" else DOMESTIC_MAIN_CONTINUOUS_SUFFIX
        return upper.endswith(expected)
    return True


def _futures_search_match(text: str, code: str, name: str, symbol: str, is_symbol: bool | None) -> bool:
    """Match a futures search query against code/name/symbol.

    With is_symbol=True the query is treated as a symbol fragment and matched
    against the native code and the user-facing symbol. Otherwise it may also
    match the Chinese product name.
    """
    if is_symbol:
        return text in code or text in symbol
    return text in code or text in symbol or text in name


# ---------------------------------------------------------------------- #
# Equity search planning / row finalization
# ---------------------------------------------------------------------- #


def _plan_equity_search(text: str) -> tuple[tuple[str, ...], str, list[tuple[str, str]] | None]:
    """Split a query into (target markets, search term, info fast-path candidates).

    A recognized market suffix narrows the target markets and is stripped from
    the term (US internal dots survive because they are unrecognized suffixes).
    Fast-path candidates are only built for unambiguous complete codes:
    six-digit CN codes and digit codes with an explicit .HK suffix.
    """
    value = text.strip().upper()
    code, suffix = split_symbol(value)
    if suffix in _EQUITY_SUFFIX_TO_MARKETS:
        markets = _EQUITY_SUFFIX_TO_MARKETS[suffix]
        term = code
        candidates: list[tuple[str, str]] | None = None
        if suffix == "HK" and code.isdigit() and code:
            padded = code.zfill(5)
            candidates = [("hk_gem" if padded.startswith("08") else "hk", padded)]
        elif suffix in SH_SUFFIXES and _is_cn_code(code):
            candidates = [("cn_sh", code)]
        elif suffix in SZ_SUFFIXES and _is_cn_code(code):
            candidates = [("cn_sz", code)]
        return markets, term, candidates
    if _is_cn_code(value):
        # Bare six-digit code: unambiguous CN, but the exchange is unknown.
        return EQUITY_SEARCH_MARKETS, value, [("cn_sh", value), ("cn_sz", value)]
    return EQUITY_SEARCH_MARKETS, value, None


def _is_cn_code(value: str) -> bool:
    return len(value) == 6 and value.isdigit()


def _equity_result_symbol(market: str, code: str) -> str:
    """Canonical user symbol for a directory row (round-trips quote/price)."""
    suffix = EQUITY_MARKET_SYMBOL_SUFFIX.get(market)
    if suffix is None:
        return code  # US keeps its code (internal dots preserved)
    return f"{code}{suffix}"


def _finalize_equity_row(row: dict[str, Any], term: str, is_symbol: bool | None) -> dict[str, Any] | None:
    """Normalize a directory row, enforcing the public search semantics.

    The service's EX search also matches the desc field; rows that only match
    through desc are dropped here. Returns None when the row does not match.
    """
    market = row.get("market")
    code = str(row.get("code") or "").strip()
    if not isinstance(market, str) or market not in EQUITY_MARKET_EXCHANGE or not code:
        raise SourceError(f"TDX equity search returned an unrecognized row (market={market!r})")
    symbol = _equity_result_symbol(market, code)
    name = row.get("name")
    name_text = str(name).strip() if name is not None else ""
    if is_symbol:
        matched = term in code.upper() or term in symbol.upper()
    else:
        matched = term in code.upper() or term in symbol.upper() or term in name_text.upper()
    if not matched:
        return None
    return {
        "symbol": symbol,
        "name": name_text or None,
        "exchange": EQUITY_MARKET_EXCHANGE[market],
        "type": None,
        "source": "tdx",
    }


def _dedup_sorted(rows: list[dict[str, Any]], key) -> list[dict[str, Any]]:
    """Stable dedup by key followed by a deterministic sort."""
    seen: set[Any] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        identity = key(row)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(row)
    unique.sort(key=key)
    return unique


# ---------------------------------------------------------------------- #
# Interval mapping
# ---------------------------------------------------------------------- #


def _service_interval(interval: str) -> str:
    """Normalize a user interval to a service-supported interval string."""
    normalized = normalize_interval(interval)
    service = SERVICE_INTERVALS.get(normalized)
    if service is None:
        raise SourceError(f"TDX unsupported interval: {interval}")
    return service


# ---------------------------------------------------------------------- #
# Row normalization
# ---------------------------------------------------------------------- #


def _is_futures_like(symbol: str) -> bool:
    return futures_exchange(symbol) is not None


def _match_quote_row(rows: list[dict[str, Any]], service_market: str, service_code: str, symbol: str) -> dict[str, Any]:
    if not rows:
        raise SourceError(f"TDX quote returned no data for {symbol}")
    for row in rows:
        if str(row.get("market") or "") == service_market and str(row.get("code") or "") == service_code:
            return row
    raise SourceError(f"TDX quote response did not include {symbol} ({service_market}/{service_code})")


def _normalize_futures_quote(row: dict[str, Any], symbol: str, meta: dict[str, Any]) -> dict[str, Any]:
    quote = _normalize_quote(row, symbol, meta)
    quote["name"] = str(row.get("name") or "").strip() or None
    return quote


def _normalize_quote(row: dict[str, Any], symbol: str, meta: dict[str, Any]) -> dict[str, Any]:
    # Explicit None checks (never `or` chains): price 0 must stay 0, not fall
    # through to a missing fallback key and collapse to None.
    price = _optional_float(row.get("price") if row.get("price") is not None else row.get("last_price"))
    prev_close = _optional_float(row.get("pre_close") if row.get("pre_close") is not None else row.get("prev_close"))
    change = price - prev_close if price is not None and prev_close not in {None, 0} else None
    return {
        "symbol": _normalize_symbol(symbol),
        "last_price": price,
        "open": _optional_float(row.get("open")),
        "high": _optional_float(row.get("high")),
        "low": _optional_float(row.get("low")),
        "prev_close": prev_close,
        "volume": _quote_volume(row.get("volume"), meta),
        "change": change,
        "change_percent": (change / prev_close * 100) if change is not None and prev_close else None,
        "source": "tdx",
    }


def _quote_volume(value: Any, meta: dict[str, Any]) -> float | None:
    """Convert quote volume using the service's declared unit metadata.

    Only verified unit declarations are converted (currently CN quotes: lot
    with lot_size=100 -> shares); unknown units keep the raw service value.
    """
    unit = meta.get("volume_unit")
    lot_size = meta.get("lot_size")
    if unit == "lot" and isinstance(lot_size, (int, float)) and lot_size > 0:
        return _optional_float(value, multiplier=float(lot_size))
    return _optional_float(value)


def _require_bar_rows(data: Any) -> list[dict[str, Any]]:
    return _require_row_dicts(data, "kline")


def _validate_page_meta(meta: dict[str, Any], rows: list[dict[str, Any]], cursor: int) -> None:
    """Contract-check list-endpoint paging metadata before trusting the cursor."""
    offset = meta.get("offset")
    limit = meta.get("limit")
    count = meta.get("count")
    complete = meta.get("complete")
    if not isinstance(complete, bool):
        raise SourceError("TDX kline meta is missing the complete flag")
    if offset != cursor:
        raise SourceError(f"TDX kline meta offset {offset!r} does not match the requested offset {cursor}")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise SourceError(f"TDX kline meta has an invalid limit: {limit!r}")
    if count != len(rows):
        raise SourceError(f"TDX kline meta count {count!r} does not match the returned {len(rows)} rows")
    next_offset = meta.get("next_offset")
    if next_offset is not None and (not isinstance(next_offset, int) or isinstance(next_offset, bool)):
        raise SourceError(f"TDX kline meta has an invalid next_offset: {next_offset!r}")


def _finalize_kline_window(
    merged: list[dict[str, Any]],
    start_date: date | None,
    end_date: date | None,
) -> list[dict[str, Any]]:
    """Apply the date window and the default newest-700 cap."""
    if start_date is not None:
        return [
            item
            for item in merged
            if _bar_date(item["date"]) >= start_date and (end_date is None or _bar_date(item["date"]) <= end_date)
        ]
    in_window = [item for item in merged if end_date is None or _bar_date(item["date"]) <= end_date]
    return in_window[-DEFAULT_KLINE_COUNT:]


def _normalize_bar_row(row: dict[str, Any], symbol: str, interval: str) -> dict[str, Any]:
    return {
        "symbol": _normalize_symbol(symbol),
        "date": _parse_bar_datetime(row.get("datetime"), interval),
        "open": _optional_float(row.get("open")),
        "high": _optional_float(row.get("high")),
        "low": _optional_float(row.get("low")),
        "close": _optional_float(row.get("close")),
        # Service values pass through untouched: units are declared per market
        # (CN/US klines = shares, HK klines = board lots, others unknown).
        "volume": _optional_float(row.get("volume")),
        "amount": _optional_float(row.get("amount")),
        "source": "tdx",
    }


def _parse_bar_datetime(value: Any, interval: str) -> date | datetime:
    text = str(value or "").strip()
    if not text:
        raise SourceError("TDX returned kline row without datetime")
    try:
        if interval in MINUTE_INTERVALS:
            return datetime.fromisoformat(text)
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise SourceError(f"TDX returned invalid kline datetime: {text!r}") from exc


def _normalize_symbol(symbol: str) -> str:
    if cn_plain_symbol(symbol) is not None:
        return to_openbb_symbol(symbol)
    return symbol.strip().upper()


def _bar_date(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def _optional_float(value: Any, *, multiplier: float = 1.0) -> float | None:
    """float coercion that preserves 0 vs null and rejects non-numeric garbage."""
    if value in {None, ""}:
        return None
    try:
        return float(value) * multiplier
    except (TypeError, ValueError) as exc:
        raise SourceError(f"TDX returned a non-numeric value: {value!r}") from exc
