"""Market data endpoints (OpenBB-style routes) proxying the Schwab REST API.

Responses pass through Schwab's JSON untouched — this service adds auth, token
hygiene, and stable naming; it deliberately does not reshape payloads.
"""

from __future__ import annotations

import datetime
import re
from typing import Callable

import requests
import schwabdev
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .client import ClientBuildError, ClientManager, NotAuthenticatedError

_UTC = datetime.timezone.utc
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: Service-facing interval -> schwabdev kwargs.
#: Minute intervals map to N-minute bars. Daily/weekly/monthly REQUIRE an
#: explicit periodType when a startDate range is used: Schwab defaults
#: periodType=DAY for range queries, which only allows minute bars (verified
#: against production: daily without periodType=year returns 400).
INTERVAL_MAP: dict[str, dict] = {
    "1m": {"frequencyType": "minute", "frequency": 1},
    "5m": {"frequencyType": "minute", "frequency": 5},
    "10m": {"frequencyType": "minute", "frequency": 10},
    "15m": {"frequencyType": "minute", "frequency": 15},
    "30m": {"frequencyType": "minute", "frequency": 30},
    "1d": {"periodType": "year", "frequencyType": "daily", "frequency": 1},
    "1w": {"periodType": "year", "frequencyType": "weekly", "frequency": 1},
    "1M": {"periodType": "year", "frequencyType": "monthly", "frequency": 1},
}

# Curated from schwabdev's validation module so errors surface as clean 422s.
_PROJECTIONS = frozenset({"symbol-search", "symbol-regex", "desc-search", "desc-regex", "search", "fundamental"})
_MOVERS_SYMBOLS = frozenset(
    {
        "$DJI",
        "$COMPX",
        "$SPX",
        "NYSE",
        "NASDAQ",
        "OTCBB",
        "INDEX_ALL",
        "EQUITY_ALL",
        "OPTION_ALL",
        "OPTION_PUT",
        "OPTION_CALL",
    }
)
_MOVERS_SORTS = frozenset({"VOLUME", "TRADES", "PERCENT_CHANGE_UP", "PERCENT_CHANGE_DOWN"})
_MOVERS_FREQUENCIES = frozenset({0, 1, 5, 10, 30, 60})
_CONTRACT_TYPES = frozenset({"CALL", "PUT", "ALL"})
_STRATEGIES = frozenset(
    {
        "SINGLE",
        "ANALYTICAL",
        "COVERED",
        "VERTICAL",
        "CALENDAR",
        "STRANGLE",
        "STRADDLE",
        "BUTTERFLY",
        "CONDOR",
        "DIAGONAL",
        "COLLAR",
        "ROLL",
    }
)
_EXP_MONTHS = frozenset({"JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC", "ALL"})
_OPTION_TYPES = frozenset({"ALL", "CALL", "PUT"})
_ENTITLEMENTS = frozenset({"PN", "NP", "PP"})
_RANGES = frozenset({"ITM", "NTM", "OTM", "SAK", "SBK", "SNK", "ALL"})
_MARKETS = frozenset({"equity", "option", "bond", "future", "forex"})


# ---- request plumbing --------------------------------------------------------


def _enforce_api_key(request: Request) -> None:
    """Optional shared-secret gate for data endpoints (auth/health/status exempt)."""
    expected = request.app.state.config.api_key
    if expected and request.headers.get("X-API-Key") != expected:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


def _require_client(request: Request) -> schwabdev.Client:
    clients: ClientManager = request.app.state.clients
    try:
        return clients.get()
    except NotAuthenticatedError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ClientBuildError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


def _proxy(call: Callable[[], requests.Response]) -> Response:
    """Run a schwabdev call and pass the raw response through, mapping errors."""
    try:
        response = call()
    except (TypeError, ValueError) as e:
        # schwabdev parameter validation failures -> client error
        raise HTTPException(status_code=422, detail=str(e)) from e
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"schwab api request failed: {e}") from e
    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=response.headers.get("content-type", "application/json"),
    )


def _parse_instant(value: str, name: str) -> datetime.datetime:
    """Parse an ISO date or datetime into an aware UTC datetime (bare date = midnight UTC)."""
    try:
        if _DATE_ONLY.match(value):
            day = datetime.date.fromisoformat(value)
            return datetime.datetime(day.year, day.month, day.day, tzinfo=_UTC)
        dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=_UTC)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"{name} must be an ISO date (YYYY-MM-DD) or datetime") from e


def _parse_date_only(value: str, name: str) -> str:
    """Validate a date param and normalize it to YYYY-MM-DD (Schwab chain format)."""
    return _parse_instant(value, name).date().isoformat()


def _validate_choice(value: str | None, name: str, choices: frozenset[str]) -> str | None:
    if value is not None and value not in choices:
        raise HTTPException(status_code=422, detail=f"{name} must be one of {sorted(choices)}")
    return value


router = APIRouter(prefix="/api/v1", tags=["market-data"], dependencies=[Depends(_enforce_api_key)])


# ---- equity ------------------------------------------------------------------


@router.get("/equity/price/quote")
def get_quote(
    symbols: str,
    fields: str | None = None,
    indicative: bool = False,
    client: schwabdev.Client = Depends(_require_client),
) -> Response:
    """Quotes for one or more comma-separated symbols."""
    return _proxy(lambda: client.quotes(symbols, fields, indicative))


@router.get("/equity/price/historical")
def get_historical(
    symbol: str,
    interval: str,
    start: str | None = None,
    end: str | None = None,
    extended: bool | None = None,
    client: schwabdev.Client = Depends(_require_client),
) -> Response:
    """Candles for a symbol; `interval` is one of 1m 5m 10m 15m 30m 1d 1w 1M.

    `start`/`end` accept ISO dates (midnight UTC) or datetimes. Schwab caps any
    single response at 40,000 candles (≈33 trading days of minute bars) and
    silently truncates from the oldest side — page long windows with `start`.
    """
    if interval not in INTERVAL_MAP:
        raise HTTPException(status_code=422, detail=f"interval must be one of {sorted(INTERVAL_MAP)}")
    extra = INTERVAL_MAP[interval]
    start_dt = _parse_instant(start, "start") if start else None
    end_dt = _parse_instant(end, "end") if end else None
    return _proxy(
        lambda: client.price_history(
            symbol=symbol,
            startDate=start_dt,
            endDate=end_dt,
            needExtendedHoursData=extended,
            **extra,
        )
    )


@router.get("/equity/search")
def get_search(
    symbol: str,
    projection: str = "symbol-search",
    client: schwabdev.Client = Depends(_require_client),
) -> Response:
    """Instrument search by symbol or description."""
    _validate_choice(projection, "projection", _PROJECTIONS)
    return _proxy(lambda: client.instruments(symbol, projection))


@router.get("/equity/fundamental")
def get_fundamental(
    symbol: str,
    client: schwabdev.Client = Depends(_require_client),
) -> Response:
    """Fundamental snapshot for a symbol (projection=fundamental)."""
    return _proxy(lambda: client.instruments(symbol, "fundamental"))


@router.get("/equity/cusip")
def get_cusip(
    cusip: str,
    client: schwabdev.Client = Depends(_require_client),
) -> Response:
    """Instrument lookup by CUSIP."""
    return _proxy(lambda: client.instrument_cusip(cusip))


@router.get("/equity/movers")
def get_movers(
    index: str,
    sort: str | None = None,
    frequency: int | None = None,
    client: schwabdev.Client = Depends(_require_client),
) -> Response:
    """Index movers; only meaningful during market hours."""
    _validate_choice(index, "index", _MOVERS_SYMBOLS)
    _validate_choice(sort, "sort", _MOVERS_SORTS)
    if frequency is not None and frequency not in _MOVERS_FREQUENCIES:
        raise HTTPException(status_code=422, detail=f"frequency must be one of {sorted(_MOVERS_FREQUENCIES)}")
    return _proxy(lambda: client.movers(index, sort, frequency))


# ---- options -----------------------------------------------------------------


@router.get("/options/chains")
def get_option_chains(
    symbol: str,
    contract_type: str | None = None,
    strike_count: int | None = None,
    include_underlying_quote: bool | None = None,
    strategy: str | None = None,
    strike_interval: str | None = None,
    strike: float | None = None,
    range: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    volatility: float | None = None,
    underlying_price: float | None = None,
    interest_rate: float | None = None,
    dte: int | None = None,
    exp_month: str | None = None,
    option_type: str | None = None,
    entitlement: str | None = None,
    client: schwabdev.Client = Depends(_require_client),
) -> Response:
    """Option chain. Large chains (e.g. SPY, unfiltered) overflow Schwab's body
    buffer — pass strike_count/dte/range to keep responses bounded."""
    _validate_choice(contract_type, "contract_type", _CONTRACT_TYPES)
    _validate_choice(strategy, "strategy", _STRATEGIES)
    _validate_choice(range, "range", _RANGES)
    _validate_choice(exp_month, "exp_month", _EXP_MONTHS)
    _validate_choice(option_type, "option_type", _OPTION_TYPES)
    _validate_choice(entitlement, "entitlement", _ENTITLEMENTS)
    return _proxy(
        lambda: client.option_chains(
            symbol=symbol,
            contractType=contract_type,
            strikeCount=strike_count,
            includeUnderlyingQuote=include_underlying_quote,
            strategy=strategy,
            interval=strike_interval,
            strike=strike,
            range=range,
            fromDate=_parse_date_only(from_date, "from_date") if from_date else None,
            toDate=_parse_date_only(to_date, "to_date") if to_date else None,
            volatility=volatility,
            underlyingPrice=underlying_price,
            interestRate=interest_rate,
            daysToExpiration=dte,
            expMonth=exp_month,
            optionType=option_type,
            entitlement=entitlement,
        )
    )


@router.get("/options/expirations")
def get_option_expirations(
    symbol: str,
    client: schwabdev.Client = Depends(_require_client),
) -> Response:
    """Available option expiration dates for a symbol."""
    return _proxy(lambda: client.option_expiration_chain(symbol))


# ---- market infrastructure ---------------------------------------------------


@router.get("/market/hours")
def get_market_hours(
    markets: str,
    date: str | None = None,
    client: schwabdev.Client = Depends(_require_client),
) -> Response:
    """Market hours for one or more comma-separated markets on an optional date."""
    for market in markets.split(","):
        _validate_choice(market.strip(), "markets", _MARKETS)
    return _proxy(lambda: client.market_hours(markets, date))
