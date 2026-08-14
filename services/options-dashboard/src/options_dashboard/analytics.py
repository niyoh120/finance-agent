"""Earnings IV Crush analytics and historical option-symbol helpers."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal, Sequence

Side = Literal["call", "put"]
QualityGrade = Literal["good", "stale", "no_trade", "outside_bounds", "no_convergence"]


# --------------------------------------------------------------------------- #
# OCC symbol + expiration helpers
# --------------------------------------------------------------------------- #

# Standard US equity option cycle: monthly expirations on the third Friday
# (Saturday historically). We compute the third Friday of a month here.


def nearest_option_expiration(after: date) -> date:
    """Return the next standard monthly expiration on or after *after*.

    Standard monthly expiration = third Friday of the month. CV uses these as
    the most liquid expirations, so candidate discovery for historical events
    starts here.
    """
    candidate = _third_friday(after.year, after.month)
    if candidate >= after:
        return candidate
    # Roll to next month.
    if after.month == 12:
        return _third_friday(after.year + 1, 1)
    return _third_friday(after.year, after.month + 1)


def _third_friday(year: int, month: int) -> date:
    # First day of month, find first Friday, add 14 days for the third.
    first = date(year, month, 1)
    first_weekday = first.weekday()  # Mon=0 .. Sun=6
    days_to_friday = (4 - first_weekday) % 7
    first_friday = first + timedelta(days=days_to_friday)
    return first_friday + timedelta(days=14)


def build_option_symbol(underlying: str, expiration: date, side: Side, strike: float) -> str:
    """Build an OCC-style option ticker understood by ConvexValue.

    Format: O:<UNDERLYING><YYMMDD><C/P><8-digit strike * 1000>
    e.g. O:AAPL260918C00100000 for AAPL 2026-09-18 call @ 100.00.
    """
    strike_int = int(round(strike * 1000))
    return f"O:{underlying.upper()}{expiration.strftime('%y%m%d')}{side[0].upper()}{strike_int:08d}"


# --------------------------------------------------------------------------- #
# Earnings IV Crush
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EarningsEvent:
    date: date
    eps_actual: float | None
    eps_estimated: float | None
    revenue_actual: float | None
    revenue_estimated: float | None


@dataclass(frozen=True)
class EarningsCrushSample:
    event: EarningsEvent
    iv_before: float | None
    iv_after: float | None
    crush_pct: float | None
    underlying_gap_pct: float | None
    quality: QualityGrade
    note: str = ""


@dataclass(frozen=True)
class CrushScenarios:
    pessimistic_gap_pct: float
    median_gap_pct: float
    optimistic_gap_pct: float
    pessimistic_crush_pct: float
    median_crush_pct: float
    optimistic_crush_pct: float
    sample_count: int
    confidence_note: str


def summarize_crush(samples: Sequence[EarningsCrushSample]) -> CrushScenarios:
    """Build three-scenario crush summary from historical samples.

    Percentiles (25/50/75) over historical gaps and crushes. Pessimistic for a
    long straddle buyer = large gap and small crush (straddle loses IV); for a
    premium seller the directions flip. We surface both and let the UI map them
    to the user's strategy.
    """
    effective_samples = [
        sample for sample in samples if sample.underlying_gap_pct is not None and sample.crush_pct is not None
    ]
    gaps = [sample.underlying_gap_pct for sample in effective_samples]
    crushes = [sample.crush_pct for sample in effective_samples]
    sample_count = len(effective_samples)

    if sample_count < 4:
        note = f"有效样本 {sample_count} < 4；仅作交互式参考，不输出统计置信结论。"
    else:
        note = f"基于 {sample_count} 次历史财报样本。"

    return CrushScenarios(
        pessimistic_gap_pct=statistics.quantiles(gaps, n=4)[0] if len(gaps) >= 2 else 0.0,
        median_gap_pct=statistics.median(gaps) if gaps else 0.0,
        optimistic_gap_pct=statistics.quantiles(gaps, n=4)[-1] if len(gaps) >= 2 else 0.0,
        pessimistic_crush_pct=statistics.quantiles(crushes, n=4)[0] if len(crushes) >= 2 else 0.0,
        median_crush_pct=statistics.median(crushes) if crushes else 0.0,
        optimistic_crush_pct=statistics.quantiles(crushes, n=4)[-1] if len(crushes) >= 2 else 0.0,
        sample_count=sample_count,
        confidence_note=note,
    )


def parse_earnings_rows(rows: Sequence[dict[str, Any]]) -> list[EarningsEvent]:
    """Normalize FMP earnings rows into :class:`EarningsEvent`."""
    events: list[EarningsEvent] = []
    for row in rows:
        d = _parse_date(row.get("date"))
        if d is None:
            continue
        events.append(
            EarningsEvent(
                date=d,
                eps_actual=_to_float(row.get("epsActual")),
                eps_estimated=_to_float(row.get("epsEstimated")),
                revenue_actual=_to_float(row.get("revenueActual")),
                revenue_estimated=_to_float(row.get("revenueEstimated")),
            )
        )
    return events


def underlying_gap_pct(closes: Sequence[tuple[date, float]], *, event_date: date, window: int = 1) -> float | None:
    """Percentage change from ``window`` days before event to ``window`` days after."""
    before = [(d, c) for d, c in closes if d < event_date]
    after = [(d, c) for d, c in closes if d > event_date]
    if not before or not after:
        return None
    before.sort(key=lambda x: x[0])
    after.sort(key=lambda x: x[0])
    pre = before[-min(window, len(before))][1]
    post = after[min(window, len(after)) - 1][1]
    if pre <= 0:
        return None
    return (post - pre) / pre


# --------------------------------------------------------------------------- #
# Small parse helpers
# --------------------------------------------------------------------------- #


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "EarningsEvent",
    "EarningsCrushSample",
    "CrushScenarios",
    "nearest_option_expiration",
    "build_option_symbol",
    "summarize_crush",
    "parse_earnings_rows",
    "underlying_gap_pct",
]
