"""Equity options chain from ConvexValue /chains.

CV returns a nested structure per underlying:
    {"chain": [{"expiration": "2026-07-17",
                "strikes": [[strike, call_fields, put_fields], ...]}]}
where call_fields/put_fields are arrays ordered by the `params` list.

We flatten this into one record per (expiration, strike, contract_type) and
expose the data as a plain list of records. We deliberately do not inherit
openbb's OptionsChainsData because that model uses a list-of-lists
serialization (each field is a parallel array) wired to
OptionsChainsProperties helpers; CV's natural unit is a single contract row,
so a flat record model is simpler and avoids fighting the base serializer.
Field names follow openbb OptionsChainsData conventions where CV has an
equivalent (midpoint -> mark, fair_market_value -> theoretical_price, etc.).
"""

from __future__ import annotations

from datetime import date as dateType
from datetime import datetime, timezone
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.models._query_coerce import ConvexValueQueryParams
from openbb_finance.sources import convexvalue as cv

# CV field name -> position in the params array. We control params via
# cv.CHAIN_FIELDS, so the index of each name is fixed for a given build.
_FIELD_INDEX: dict[str, int] = {name: idx for idx, name in enumerate(cv.CHAIN_FIELDS)}


class FinanceOptionsChainQueryParams(ConvexValueQueryParams):
    """Options chain query (symbol only)."""

    symbol: str = Field(description=QUERY_DESCRIPTIONS.get("symbol", ""))


class FinanceOptionsChainData(Data):
    """One option contract row from the ConvexValue chain.

    Field aliases map CV names to openbb OptionsChainsData conventions:
    midpoint is the bid/ask mid-price (openbb `mark`); fair_market_value is
    CV's model price (openbb `theoretical_price`); day_volume is the per-
    contract trade volume (openbb `volume`).
    """

    symbol: str = Field(description="Underlying ticker.")
    contract_symbol: str = Field(description="OCC-style option contract symbol.")
    expiration: dateType = Field(description="Contract expiration date.")
    strike: float = Field(description="Strike price.")
    option_type: str = Field(description="'call' or 'put'.")
    # greeks + IV
    delta: float | None = Field(default=None)
    gamma: float | None = Field(default=None)
    theta: float | None = Field(default=None)
    vega: float | None = Field(default=None)
    implied_volatility: float | None = Field(default=None)
    # pricing
    bid: float | None = Field(default=None)
    bid_size: float | None = Field(default=None)
    ask: float | None = Field(default=None)
    ask_size: float | None = Field(default=None)
    mark: float | None = Field(default=None, description="Mid-price (CV midpoint).")
    theoretical_price: float | None = Field(default=None, description="Model price (CV fair_market_value).")
    break_even_price: float | None = Field(default=None)
    # open interest + volume
    open_interest: float | None = Field(default=None)
    volume: float | None = Field(default=None, description="Day volume (CV day_volume).")
    # day stats
    open: float | None = Field(default=None, description="Day open (CV day_open).")
    high: float | None = Field(default=None, description="Day high (CV day_high).")
    low: float | None = Field(default=None, description="Day low (CV day_low).")
    close: float | None = Field(default=None, description="Day close (CV day_close).")
    prev_close: float | None = Field(default=None, description="CV day_previous_close.")
    change: float | None = Field(default=None)
    change_percent: float | None = Field(default=None)
    vwap: float | None = Field(default=None, description="Day VWAP (CV day_vwap).")
    # contract metadata
    exercise_style: str | None = Field(default=None)
    contract_size: float | None = Field(default=None, description="Shares per contract (CV shares_per_contract).")
    # underlying
    underlying_symbol: str | None = Field(default=None)
    underlying_price: float | None = Field(default=None)
    underlying_change_to_break_even: float | None = Field(default=None)
    last_trade_price: float | None = Field(default=None, description="CV trade_price.")
    dte: int | None = Field(default=None, description="Days to expiration (computed).")
    fetched_at: datetime | None = Field(default=None)


class FinanceOptionsChainFetcher(Fetcher[FinanceOptionsChainQueryParams, list[FinanceOptionsChainData]]):
    """Fetcher for ConvexValue options chains."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceOptionsChainQueryParams:
        return FinanceOptionsChainQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceOptionsChainQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Return {'records': [...], 'contract_count': N}.

        contract_count is the server-reported total (pre-filtering); records
        are flattened per-contract dicts. Keeping both on one dict so callers
        that want the total (e.g. the CLI _meta payload) can read it without a
        second request.
        """
        del credentials, kwargs
        raw = await cv.fetch_chains(query.symbol)
        return {"records": _flatten_chain(raw), "contract_count": raw.get("contract_count", 0)}

    @staticmethod
    def transform_data(
        query: FinanceOptionsChainQueryParams,
        data: dict[str, Any],
        **kwargs: Any,
    ) -> list[FinanceOptionsChainData]:
        del query, kwargs
        records = data.get("records", []) if isinstance(data, dict) else data
        if not records:
            raise EmptyDataError()
        return [FinanceOptionsChainData.model_validate(row) for row in records]


def _flatten_chain(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand the CV nested chain into one dict per contract.

    Each strike row is [strike_price, call_field_array, put_field_array]; we
    emit two records (call + put) and skip contracts whose call/put side is
    entirely empty (CV returns arrays of None for illiquid strikes).
    """
    today = datetime.now(timezone.utc).date()
    records: list[dict[str, Any]] = []
    for expiration_block in raw.get("chain", []):
        expiration = _parse_date(expiration_block.get("expiration"))
        if expiration is None:
            continue
        dte = max((expiration - today).days, 0)
        for strike_row in expiration_block.get("strikes", []):
            if not isinstance(strike_row, list) or len(strike_row) < 3:
                continue
            strike = strike_row[0]
            call_fields = strike_row[1]
            put_fields = strike_row[2]
            if isinstance(call_fields, list) and _has_data(call_fields):
                records.append(
                    _row_to_dict(
                        call_fields,
                        query_symbol=str(raw.get("symbol", "")),
                        strike=strike,
                        expiration=expiration,
                        dte=dte,
                        fallback_option_type="call",
                    )
                )
            if isinstance(put_fields, list) and _has_data(put_fields):
                records.append(
                    _row_to_dict(
                        put_fields,
                        query_symbol=str(raw.get("symbol", "")),
                        strike=strike,
                        expiration=expiration,
                        dte=dte,
                        fallback_option_type="put",
                    )
                )
    return records


def _has_data(field_array: list[Any]) -> bool:
    # CV fills illiquid strikes with arrays of None; treat those as empty.
    return any(value is not None for value in field_array)


def _row_to_dict(
    fields: list[Any],
    *,
    query_symbol: str,
    strike: float,
    expiration: dateType | None,
    dte: int | None,
    fallback_option_type: str | None = None,
) -> dict[str, Any]:
    def pick(cv_name: str) -> Any:
        idx = _FIELD_INDEX.get(cv_name)
        return fields[idx] if idx is not None and idx < len(fields) else None

    contract_symbol = pick("ticker") or ""
    option_type = pick("contract_type") or fallback_option_type
    return {
        "symbol": query_symbol,
        "contract_symbol": contract_symbol,
        "expiration": expiration,
        "strike": strike,
        "option_type": option_type,
        "delta": pick("delta"),
        "gamma": pick("gamma"),
        "theta": pick("theta"),
        "vega": pick("vega"),
        "implied_volatility": pick("implied_volatility"),
        "bid": pick("bid"),
        "bid_size": pick("bid_size"),
        "ask": pick("ask"),
        "ask_size": pick("ask_size"),
        "mark": pick("midpoint"),
        "theoretical_price": pick("fair_market_value"),
        "break_even_price": pick("break_even_price"),
        "open_interest": pick("open_interest"),
        "volume": pick("day_volume"),
        "open": pick("day_open"),
        "high": pick("day_high"),
        "low": pick("day_low"),
        "close": pick("day_close"),
        "prev_close": pick("day_previous_close"),
        "change": pick("day_change"),
        "change_percent": pick("day_change_percent"),
        "vwap": pick("day_vwap"),
        "exercise_style": pick("exercise_style"),
        "contract_size": pick("shares_per_contract"),
        "underlying_symbol": pick("underlying_symbol"),
        "underlying_price": pick("underlying_price"),
        "underlying_change_to_break_even": pick("underlying_change_to_break_even"),
        "last_trade_price": pick("trade_price"),
        "dte": dte,
        "fetched_at": _parse_datetime(pick("fetched_at")),
    }


def _parse_date(value: Any) -> dateType | None:
    if value is None:
        return None
    if isinstance(value, dateType):
        return value
    text = str(value)
    if not text:
        return None
    try:
        return dateType.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value)
    if not text or not text.isdigit():
        return None
    # CV timestamps are nanoseconds since epoch; truncate to microseconds.
    try:
        return datetime.fromtimestamp(int(text) / 1e9, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None
