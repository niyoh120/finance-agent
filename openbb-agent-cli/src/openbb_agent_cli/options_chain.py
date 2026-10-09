"""Options-chain query model, validation, and pure post-processing.

Shared brain of ``derivatives.options.chain`` for the direct CLI command and
the batch executor: explicit request types, named constants, strict parameter
validation, date-window resolution, Schwab record normalization, CV field-
enrichment preparation/apply, and ATM strike selection. Network access and
output shaping live in :mod:`openbb_agent_cli.executors`; everything here is
pure (no I/O). The single UTC ``as_of_date`` freeze happens once per request
in :func:`build_options_chain_request`.

Contract-set invariant: the Schwab chain is the ONLY source of contracts.
CV participates purely as a field-filler for Schwab-matched keys, so the
result key set is always a subset of the (date-filtered) Schwab key set.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from openbb_finance.sources.base import SourceError

# ---- product constants -------------------------------------------------------

#: DTE-mode defaults when neither/one endpoint is provided explicitly.
DEFAULT_DTE_MIN = 0
DEFAULT_DTE_MAX = 45
#: Maximum distance between dte_min and dte_max (endpoints included).
MAX_DTE_SPAN = 365

#: ATM selection: strikes kept per expiration (call/put share the strike set).
DEFAULT_ATM = 20
MIN_ATM = 1
MAX_ATM = 100

DEFAULT_SORT_BY = "open_interest"
DEFAULT_SORT_DIR = "desc"
SORT_FIELDS: tuple[str, ...] = (
    "expiration",
    "strike",
    "open_interest",
    "volume",
    "implied_volatility",
    "delta",
    "bid",
    "ask",
    "vwap",
)
OPTION_TYPES: tuple[str, ...] = ("call", "put")

#: Output row cap: direct CLI default vs batch sub-query default. An explicit
#: ``limit=0`` means "all filtered contracts".
CLI_DEFAULT_LIMIT = 50
BATCH_DEFAULT_LIMIT = 100

#: Contract identity: the cross-source match key and the Schwab anchor.
IDENTITY_FIELDS: tuple[str, ...] = ("expiration", "strike", "option_type")
ChainKey = tuple[date, float, str]

#: Fields CV may fill on Schwab-matched contracts: the unified chain model's
#: non-identity fields minus the query symbol and the derived dte (both are
#: maintained by the query logic). Keep in sync with
#: openbb_finance.models.equity_options_chain.FinanceOptionsChainData.
ENRICHABLE_FIELDS: frozenset[str] = frozenset(
    {
        "contract_symbol",
        "delta",
        "gamma",
        "theta",
        "vega",
        "implied_volatility",
        "bid",
        "bid_size",
        "ask",
        "ask_size",
        "mark",
        "theoretical_price",
        "break_even_price",
        "open_interest",
        "volume",
        "open",
        "high",
        "low",
        "close",
        "prev_close",
        "change",
        "change_percent",
        "vwap",
        "exercise_style",
        "contract_size",
        "underlying_symbol",
        "underlying_price",
        "underlying_change_to_break_even",
        "last_trade_price",
        "fetched_at",
    }
)

# ---- batch param surface -----------------------------------------------------

#: Batch params accepted by the options.chain sub-query.
BATCH_CHAIN_FIELDS: frozenset[str] = frozenset(
    {"symbol", "expiration", "dte_min", "dte_max", "atm", "option_type", "sort_by", "sort_dir", "limit"}
)

#: Legacy batch params removed by the redesign, with their migration hint.
REMOVED_FIELD_HINTS: dict[str, str] = {
    "dte": "use dte_min/dte_max",
    "min_dte": "use dte_min",
    "strike_count": "use atm",
    "range": "removed (Schwab-side range filter)",
    "range_": "removed (Schwab-side range filter)",
    "strategy": "removed (Schwab-side strategy filter)",
}

# ---- request types -----------------------------------------------------------


@dataclass(frozen=True)
class DateWindow:
    """Resolved query window anchored to one frozen UTC ``as_of_date``.

    ``mode`` is ``"expiration"`` (single day, ``from == to``) or ``"dte"``
    (absolute endpoints derived from ``as_of_date + dte_min/max``).
    """

    mode: str
    as_of_date: date
    from_date: date
    to_date: date
    expiration: date | None = None
    dte_min: int | None = None
    dte_max: int | None = None

    @property
    def span(self) -> int:
        return (self.to_date - self.from_date).days

    def contains(self, expiration: date) -> bool:
        return self.from_date <= expiration <= self.to_date

    def meta(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "mode": self.mode,
            "as_of_date": self.as_of_date.isoformat(),
            "timezone": "UTC",
            "from_date": self.from_date.isoformat(),
            "to_date": self.to_date.isoformat(),
            "span": self.span,
        }
        if self.mode == "dte":
            payload["dte_min"] = self.dte_min
            payload["dte_max"] = self.dte_max
        else:
            payload["expiration"] = self.expiration.isoformat() if self.expiration else None
        return payload


@dataclass(frozen=True)
class OptionsChainRequest:
    """Fully validated options.chain query (no network knowledge)."""

    symbol: str
    window: DateWindow
    atm: int
    option_type: str | None
    sort_by: str
    sort_dir: str
    limit: int | None


# ---- scalar coercion ---------------------------------------------------------


def _require_int(value: Any, name: str) -> int:
    """Strict integer check: bools and floats are rejected (batch JSON safety)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer; got {value!r}")
    return value


def _require_non_negative_int(value: Any, name: str) -> int:
    number = _require_int(value, name)
    if number < 0:
        raise ValueError(f"{name} must be a non-negative integer; got {value!r}")
    return number


def _require_choice(value: Any, name: str, choices: tuple[str, ...]) -> str:
    if value not in choices:
        raise ValueError(f"{name} must be one of {list(choices)}; got {value!r}")
    return str(value)


def _parse_iso_date(value: Any, name: str) -> date:
    """Strict ``YYYY-MM-DD`` parsing (``date.fromisoformat`` alone also accepts
    compact forms like ``20260909``, which we reject for CLI unambiguity)."""
    text = value if isinstance(value, str) else str(value)
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        raise ValueError(f"{name} must use the strict YYYY-MM-DD format; got {value!r}")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{name} must use the strict YYYY-MM-DD format; got {value!r}") from None


def _coerce_expiration(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _coerce_strike(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _coerce_option_type(value: Any) -> str | None:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in OPTION_TYPES:
            return lowered
    return None


def _coerce_price(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


# ---- window resolution -------------------------------------------------------


def resolve_date_window(
    *,
    expiration: Any = None,
    dte_min: Any = None,
    dte_max: Any = None,
    as_of_date: date,
) -> DateWindow:
    """Resolve the two mutually exclusive query modes into a DateWindow.

    - ``expiration``: strict YYYY-MM-DD, today (UTC) or later; exact window
      ``[expiration, expiration]``.
    - ``dte_min``/``dte_max``: defaults 0/45 fill missing endpoints, then
      non-negative/order/span checks run; endpoints are inclusive and the
      window is converted to absolute dates on the frozen ``as_of_date``.
    """
    if expiration is not None and (dte_min is not None or dte_max is not None):
        raise ValueError("--expiration is mutually exclusive with --dte-min/--dte-max; choose one query mode")

    if expiration is not None:
        exp = _parse_iso_date(expiration, "expiration")
        if exp < as_of_date:
            raise ValueError(
                f"expiration must be today or later (UTC as_of {as_of_date.isoformat()}); got {exp.isoformat()}"
            )
        return DateWindow(mode="expiration", as_of_date=as_of_date, from_date=exp, to_date=exp, expiration=exp)

    lo = DEFAULT_DTE_MIN if dte_min is None else _require_non_negative_int(dte_min, "dte_min")
    hi = DEFAULT_DTE_MAX if dte_max is None else _require_non_negative_int(dte_max, "dte_max")
    if lo > hi:
        hint = ""
        if dte_max is None:
            hint = (
                f" (dte_max defaulted to {DEFAULT_DTE_MAX}; provide dte_max explicitly "
                "for far-dated windows, e.g. dte_min=700 dte_max=1000)"
            )
        raise ValueError(f"dte_min must be <= dte_max; got dte_min={lo}, dte_max={hi}{hint}")
    if hi - lo > MAX_DTE_SPAN:
        raise ValueError(
            f"dte window span must be <= {MAX_DTE_SPAN} days; got dte_min={lo}, dte_max={hi} (span {hi - lo})"
        )
    try:
        from_day = as_of_date + timedelta(days=lo)
        to_day = as_of_date + timedelta(days=hi)
    except OverflowError:
        raise ValueError(
            f"dte window {lo}..{hi} overflows the representable date range from {as_of_date.isoformat()}"
        ) from None
    return DateWindow(
        mode="dte",
        as_of_date=as_of_date,
        from_date=from_day,
        to_date=to_day,
        dte_min=lo,
        dte_max=hi,
    )


# ---- request building --------------------------------------------------------


def build_options_chain_request(
    *,
    symbol: Any,
    expiration: Any = None,
    dte_min: Any = None,
    dte_max: Any = None,
    atm: Any = DEFAULT_ATM,
    option_type: Any = None,
    sort_by: Any = DEFAULT_SORT_BY,
    sort_dir: Any = DEFAULT_SORT_DIR,
    limit: Any = None,
    as_of_date: date | None = None,
) -> OptionsChainRequest:
    """Validate every parameter BEFORE any network access and freeze the query.

    ``limit`` accepts non-negative integers; ``None``/``0`` both mean "all
    filtered contracts". ``as_of_date`` defaults to one UTC freeze.
    """
    text = symbol if isinstance(symbol, str) else str(symbol or "")
    symbol_text = text.strip().upper()
    if not symbol_text:
        raise ValueError("symbol is required")

    frozen = as_of_date if as_of_date is not None else datetime.now(timezone.utc).date()
    window = resolve_date_window(expiration=expiration, dte_min=dte_min, dte_max=dte_max, as_of_date=frozen)

    atm_value = DEFAULT_ATM if atm is None else _require_int(atm, "atm")
    if not (MIN_ATM <= atm_value <= MAX_ATM):
        raise ValueError(f"atm must be between {MIN_ATM} and {MAX_ATM}; got {atm_value}")

    option_type_value = None if option_type is None else _require_choice(option_type, "option_type", OPTION_TYPES)
    sort_by_value = DEFAULT_SORT_BY if sort_by is None else _require_choice(sort_by, "sort_by", SORT_FIELDS)
    sort_dir_value = DEFAULT_SORT_DIR if sort_dir is None else _require_choice(sort_dir, "sort_dir", ("asc", "desc"))

    if limit is None:
        limit_value: int | None = None
    else:
        limit_value = _require_non_negative_int(limit, "limit")
        if limit_value == 0:
            limit_value = None

    return OptionsChainRequest(
        symbol=symbol_text,
        window=window,
        atm=atm_value,
        option_type=option_type_value,
        sort_by=sort_by_value,
        sort_dir=sort_dir_value,
        limit=limit_value,
    )


def normalize_batch_chain_params(params: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the batch sub-query param object and drop unspecified values.

    ``source`` is rejected in ANY form (even explicit null): the chain query
    always uses the Schwab contract set with CV field enrichment. Legacy
    window params and unknown fields get a migration error; ``None`` values
    are treated as "unspecified" and removed so defaults apply.
    """
    if "source" in params:
        raise ValueError(
            "params.source is no longer supported: options.chain always uses the Schwab "
            "contract set with optional CV field enrichment"
        )
    unknown = sorted(set(params) - BATCH_CHAIN_FIELDS)
    if unknown:
        hints = [f"{field}: {REMOVED_FIELD_HINTS[field]}" for field in unknown if field in REMOVED_FIELD_HINTS]
        known = sorted(BATCH_CHAIN_FIELDS)
        message = f"unknown or removed options.chain batch params: {unknown}; known params: {known}"
        if hints:
            message = (
                f"unknown or removed options.chain batch params: {unknown} ({'; '.join(hints)}); known params: {known}"
            )
        raise ValueError(message)
    return {key: value for key, value in params.items() if value is not None}


# ---- Schwab record normalization ---------------------------------------------


def _contract_identity(record: Mapping[str, Any], *, origin: str) -> ChainKey:
    """Extract and validate ``(expiration, strike, option_type)``.

    Missing/invalid identity on a Schwab record is a primary-query data error
    (SourceError); callers treat CV rows with invalid identity as ignorable.
    """
    expiration = _coerce_expiration(record.get("expiration"))
    strike = _coerce_strike(record.get("strike"))
    option_type = _coerce_option_type(record.get("option_type"))
    if expiration is None or strike is None or option_type is None:
        raise SourceError(
            f"{origin} chain returned a contract with missing or invalid identity fields "
            f"(expiration/strike/option_type): expiration={record.get('expiration')!r}, "
            f"strike={record.get('strike')!r}, option_type={record.get('option_type')!r}"
        )
    return (expiration, strike, option_type)


def normalize_schwab_chain_records(
    records: Iterable[Mapping[str, Any]],
    *,
    window: DateWindow,
) -> list[dict[str, Any]]:
    """Validate identity, dedupe keys, filter by window, normalize dte.

    - identity validation failures raise SourceError (primary-query data error);
    - duplicate Schwab keys keep the first row position and take the first
      non-None value per field, so each key is emitted exactly once;
    - records outside ``[window.from_date, window.to_date]`` are dropped;
    - ``dte`` is recomputed as ``(expiration - as_of_date).days`` (upstream
      values are never trusted).
    """
    ordered: list[dict[str, Any]] = []
    by_key: dict[ChainKey, dict[str, Any]] = {}
    for record in records:
        key = _contract_identity(record, origin="Schwab")
        existing = by_key.get(key)
        if existing is None:
            row = dict(record)
            row["expiration"] = key[0]
            row["strike"] = key[1]
            row["option_type"] = key[2]
            by_key[key] = row
            ordered.append(row)
            continue
        for field, value in record.items():
            if existing.get(field) is None and value is not None:
                existing[field] = value

    selected = [row for row in ordered if window.contains(row["expiration"])]
    for row in selected:
        row["dte"] = (row["expiration"] - window.as_of_date).days
    return selected


# ---- CV field enrichment (Schwab-left join) -----------------------------------


def build_cv_enrichment(
    schwab_records: Iterable[Mapping[str, Any]],
    cv_records: Iterable[Mapping[str, Any]],
) -> dict[ChainKey, dict[str, Any]]:
    """Prepare CV fill values for Schwab-matched keys ONLY.

    CV rows with invalid identity are ignored; CV-only contracts are ignored
    even when their expiration/ATM range would match the query. For repeated
    CV keys the first non-None value per enrichable field wins in CV order.
    """
    available = {_contract_identity(record, origin="Schwab") for record in schwab_records}
    enrichment: dict[ChainKey, dict[str, Any]] = {}
    for record in cv_records:
        try:
            key = _contract_identity(record, origin="CV")
        except SourceError:
            continue
        if key not in available:
            continue
        patch = enrichment.setdefault(key, {})
        for field in ENRICHABLE_FIELDS:
            if patch.get(field) is not None:
                continue
            value = record.get(field)
            if value is not None:
                patch[field] = value
    return enrichment


def apply_cv_enrichment(
    schwab_records: Iterable[Mapping[str, Any]],
    enrichment: Mapping[ChainKey, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Copy the Schwab rows and fill missing/None fields from the prepared map.

    Existing non-None values (0/False/empty string included) are preserved.
    Applying happens once, after preparation has fully succeeded, so a CV
    failure mid-way can never produce partially enriched rows.
    """
    result: list[dict[str, Any]] = []
    for record in schwab_records:
        key = _contract_identity(record, origin="Schwab")
        row = dict(record)
        patch = enrichment.get(key)
        if patch:
            for field, value in patch.items():
                if row.get(field) is None:
                    row[field] = value
        result.append(row)
    return result


# ---- ATM selection ------------------------------------------------------------


def resolve_reference_price(records: Iterable[Mapping[str, Any]]) -> float | None:
    """Pick one finite reference price, deterministically.

    Preference: Schwab rows carry ``underlying_price`` from the primary
    response; CV-enriched rows (price missing on the Schwab side) participate
    through the same field after enrichment. Candidates are ordered by
    ``(expiration, strike, option_type)`` so the choice is stable.
    """
    ordered = sorted(records, key=lambda row: (row["expiration"], row["strike"], row["option_type"]))
    for row in ordered:
        price = _coerce_price(row.get("underlying_price"))
        if price is not None:
            return price
    return None


def select_atm_strikes(
    records: Iterable[Mapping[str, Any]],
    *,
    atm: int,
    reference_price: float,
) -> list[dict[str, Any]]:
    """Keep, per expiration, the *atm* strike levels nearest the reference.

    Ties pick the lower strike; sparse expirations keep all their levels;
    call/put rows share the kept strike set. Input record order is preserved.
    """
    strikes_by_expiration: dict[date, set[float]] = {}
    for record in records:
        strikes_by_expiration.setdefault(record["expiration"], set()).add(record["strike"])
    kept: set[tuple[date, float]] = set()
    for expiration, strikes in strikes_by_expiration.items():
        ordered = sorted(strikes, key=lambda strike: (abs(strike - reference_price), strike))
        for strike in ordered[:atm]:
            kept.add((expiration, strike))
    return [record for record in records if (record["expiration"], record["strike"]) in kept]
