"""Schwab option chain flattening to FinanceOptionsChainData-shaped records.

Schwab /options/chains returns a nested structure::

    {"symbol": "AAPL",
     "underlyingPrice": 319.97,
     "callExpDateMap": {"2026-09-09:3": {"317.5": [contract, ...]}},
     "putExpDateMap": {"2026-09-09:3": {...}}}

The outer map key is "YYYY-MM-DD:N" (expiration : days-to-expiration); the
inner key is the strike as a string; each contract is a flat JSON object.

We emit one dict per contract following the same field conventions as the CV
chain model (models/equity_options_chain.py), because the CLI aggregates both
sources on (expiration, strike, option_type):

- option_type is lowercase "call"/"put" (Schwab putCall is CALL/PUT)
- implied_volatility is a decimal; Schwab volatility is a percent -> /100
- exercise_style is "american"/"european" (Schwab exerciseType is A/E)
- expiration is a datetime.date so cross-source aggregation keys align
- fetched_at carries the per-contract quote timestamp (quoteTimeInLong, ms
  epoch) — the only freshness signal Schwab provides
"""

from __future__ import annotations

from datetime import date as dateType
from datetime import datetime, timezone
from typing import Any

# Schwab exerciseType A (American) / E (European) -> CV-style lowercase style.
_EXERCISE_TYPE_MAP = {"A": "american", "E": "european"}


def flatten_schwab_chain(raw: dict[str, Any], *, query_symbol: str | None = None) -> list[dict[str, Any]]:
    """Expand the Schwab nested chain into one dict per contract."""
    if not isinstance(raw, dict):
        return []
    underlying = (query_symbol or str(raw.get("symbol") or "")).strip().upper()
    underlying_price = _optional_float(raw.get("underlyingPrice"))
    records: list[dict[str, Any]] = []
    for map_key, fallback_type in (("callExpDateMap", "call"), ("putExpDateMap", "put")):
        expirations = raw.get(map_key)
        if not isinstance(expirations, dict):
            continue
        for exp_key, strikes in expirations.items():
            expiration = _parse_exp_key(exp_key)
            if expiration is None or not isinstance(strikes, dict):
                continue
            for _strike_key, contracts in strikes.items():
                if not isinstance(contracts, list):
                    continue
                for contract in contracts:
                    if isinstance(contract, dict):
                        records.append(
                            _contract_to_dict(
                                contract,
                                underlying=underlying,
                                underlying_price=underlying_price,
                                expiration=expiration,
                                fallback_option_type=fallback_type,
                            )
                        )
    return records


def _contract_to_dict(
    contract: dict[str, Any],
    *,
    underlying: str,
    underlying_price: float | None,
    expiration: dateType,
    fallback_option_type: str,
) -> dict[str, Any]:
    option_type = str(contract.get("putCall") or fallback_option_type).lower()
    option_type = "call" if option_type.startswith("c") else "put"
    # Schwab returns a -999 sentinel volatility for contracts without an IV;
    # normalize to None so the CV-side convention (null) is preserved.
    volatility = _optional_float(contract.get("volatility"))
    if volatility is not None and volatility <= 0:
        volatility = None
    exercise_type = contract.get("exerciseType")
    return {
        "symbol": underlying,
        "underlying_symbol": underlying,
        "underlying_price": underlying_price,
        "contract_symbol": str(contract.get("symbol") or "").replace(" ", ""),
        "expiration": expiration,
        "strike": _optional_float(contract.get("strikePrice")),
        "option_type": option_type,
        # greeks + IV (Schwab volatility is a percent; normalize to the CV
        # decimal convention: 25.62 -> 0.2562)
        "delta": _optional_float(contract.get("delta")),
        "gamma": _optional_float(contract.get("gamma")),
        "theta": _optional_float(contract.get("theta")),
        "vega": _optional_float(contract.get("vega")),
        "implied_volatility": volatility / 100.0 if volatility is not None else None,
        # pricing
        "bid": _optional_float(contract.get("bid")),
        "bid_size": _optional_float(contract.get("bidSize")),
        "ask": _optional_float(contract.get("ask")),
        "ask_size": _optional_float(contract.get("askSize")),
        "mark": _optional_float(contract.get("mark")),
        "theoretical_price": _optional_float(contract.get("theoreticalOptionValue")),
        "break_even_price": _optional_float(contract.get("breakEven")),
        # open interest + volume
        "open_interest": _optional_float(contract.get("openInterest")),
        "volume": _optional_float(contract.get("totalVolume")),
        # day stats (Schwab's open/high/low/close are the prior session's)
        "open": _optional_float(contract.get("openPrice")),
        "high": _optional_float(contract.get("highPrice")),
        "low": _optional_float(contract.get("lowPrice")),
        "close": _optional_float(contract.get("closePrice")),
        "change": _optional_float(contract.get("netChange")),
        "change_percent": _optional_float(contract.get("percentChange")),
        # contract metadata
        "exercise_style": _EXERCISE_TYPE_MAP.get(str(exercise_type or "").strip().upper()),
        "contract_size": _optional_float(contract.get("multiplier")),
        "last_trade_price": _optional_float(contract.get("last")),
        "dte": contract.get("daysToExpiration"),
        "fetched_at": _ms_epoch_to_datetime(contract.get("quoteTimeInLong")),
    }


def _parse_exp_key(exp_key: Any) -> dateType | None:
    """Parse the map key "2026-09-09:3" into a date."""
    text = str(exp_key or "").split(":", 1)[0].strip()
    if not text:
        return None
    try:
        return dateType.fromisoformat(text)
    except ValueError:
        return None


def _ms_epoch_to_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (OSError, OverflowError, TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
