"""Shared input contracts and intraday quality gates for historical models.

Used by the finance index/ETF historical fetchers (and reusable for other
routed historical models): interval normalization with per-market capability
bounds, and minute-bar temporal sanity checks applied per source inside the
fetch loop so a broken source result falls through to the next candidate.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from openbb_finance.sources.base import Market, is_intraday_interval, normalize_interval

#: Intervals the routed index/ETF minute chain accepts. ``1d`` default keeps
#: the pre-existing daily behaviour; ``1w``/``1M`` ride the existing daily+
#: source chains.
BASE_INTERVALS: frozenset[str] = frozenset({"1m", "5m", "15m", "30m", "60m", "1d", "1w", "1M"})
#: Schwab-only granularity: TDX serves no 10m bars, so 10m is accepted for US
#: symbols only and rejected for CN/HK at model validation time.
US_EXTRA_INTERVALS: frozenset[str] = frozenset({"10m"})

_MIDNIGHT = time(0, 0)


def normalize_query_interval(interval: str, *, market: Market) -> str:
    """Validate and canonicalize the query interval for a routed historical query.

    Numeric minute aliases resolve through the shared ``normalize_interval``
    (``"5"`` -> ``"5m"``); the hour alias ``1h``/``1H`` is unified to ``60m`` at
    the model layer while sources keep their own mappings. Unknown intervals —
    and 10m outside the US market — fail here, before any network request.
    """
    value = (interval or "").strip()
    if not value:
        raise ValueError("interval must not be empty; use e.g. '1d' (default) or '5m'")
    normalized = normalize_interval(value)
    if normalized.lower() == "1h":
        normalized = "60m"
    allowed = BASE_INTERVALS | (US_EXTRA_INTERVALS if market == "us" else frozenset())
    if normalized not in allowed:
        supported = ", ".join(sorted(allowed))
        raise ValueError(f"unsupported interval {interval!r} for {market} symbols; supported intervals: {supported}")
    return normalized


def is_minute_interval(interval: str) -> bool:
    """True when *interval* (already canonical or a common alias) is minute-grained.

    Wraps the shared ``is_intraday_interval`` so the month label ``1M`` (and
    other month/quarter/year aliases) classify as non-intraday.
    """
    return is_intraday_interval(normalize_interval(interval))


def validate_intraday_rows(rows: list[dict[str, Any]], *, symbol: str, interval: str) -> None:
    """Raise ``ValueError`` when minute rows fail temporal sanity checks.

    Applied per source inside the fetch loop, after the source returns and
    before the result can win, so a source that returns unusable minute bars
    (date-only rows, duplicates, descending order, or a whole day collapsed
    onto midnight) is skipped instead of being served as a successful
    fallback. A single legitimate midnight bar stays allowed; only a date
    carrying multiple bars that are ALL stamped 00:00:00 is treated as the
    known TDX 1m time-collapse defect.
    """
    if not rows:
        raise ValueError(f"{symbol} {interval} returned no rows")
    previous: datetime | None = None
    seen_dates: dict[date, list[datetime]] = {}
    for index, row in enumerate(rows):
        value = row.get("date")
        if not isinstance(value, datetime):
            raise ValueError(
                f"{symbol} {interval} row {index} has a date-only or missing timestamp ({type(value).__name__})"
            )
        if previous is not None and value <= previous:
            raise ValueError(f"{symbol} {interval} bars are not strictly ascending at {value.isoformat()}")
        previous = value
        seen_dates.setdefault(value.date(), []).append(value)
    for day, stamps in seen_dates.items():
        if len(stamps) > 1 and all(stamp.time() == _MIDNIGHT for stamp in stamps):
            raise ValueError(
                f"{symbol} {interval} collapsed {len(stamps)} bars on {day.isoformat()} to midnight "
                "(source time decoding failure)"
            )
