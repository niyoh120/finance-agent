"""Market-data adapters that feed the pricing core.

Bridges FMP ``treasury-rates`` / ``profile`` shapes into the scalar inputs the
pricing functions need (risk-free rate for a given DTE, continuous dividend
yield, exercise style). Keeps pricing.py pure-numeric so it can be unit-tested
without any data source.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Sequence

from .pricing import Style

logger = logging.getLogger(__name__)

# Fallback rate (annualized, continuously-compounded convention used by BSM/CRR)
# when Treasury data is unavailable. Conservative; surfaced to the UI so users
# know the assumption.
FALLBACK_RATE = 0.04

# Pillar tenors (in years) that FMP reports. ``monthN`` and ``yearN`` columns
# are percentage annual yields; we interpolate in linear-tenor space.
# ponytail: simple linear interpolation across a fixed pillar set is accurate
# enough for equity-option pricing; swap to a spline if rates-driven books
# ever need it.
_TREASURY_PILLARS: tuple[tuple[str, float], ...] = (
    ("month1", 1 / 12),
    ("month2", 2 / 12),
    ("month3", 3 / 12),
    ("month6", 6 / 12),
    ("year1", 1.0),
    ("year2", 2.0),
    ("year3", 3.0),
    ("year5", 5.0),
    ("year7", 7.0),
    ("year10", 10.0),
    ("year20", 20.0),
    ("year30", 30.0),
)


def interpolate_rate(
    rows: Sequence[dict[str, Any]] | None,
    *,
    tenor_years: float,
    as_of: str | None = None,
) -> tuple[float, str]:
    """Interpolate a risk-free rate for *tenor_years* from FMP treasury rows.

    Returns ``(rate, source)`` where ``source`` describes the provenance so the
    UI can show assumptions. Falls back to :data:`FALLBACK_RATE` on any problem.
    """
    if not rows:
        return FALLBACK_RATE, "fallback(no-data)"
    # Pick the most recent curve <= as_of when provided (rows are desc by date).
    curve = _select_curve(rows, as_of)
    if not curve:
        return FALLBACK_RATE, "fallback(no-matching-date)"
    pillars = [
        (tenor, float(curve[col]) / 100.0)
        for col, tenor in _TREASURY_PILLARS
        if col in curve and _is_number(curve[col])
    ]
    if not pillars:
        return FALLBACK_RATE, "fallback(no-pillars)"
    pillars.sort()
    return _linear_interp(pillars, tenor_years), "treasury-interp"


def _select_curve(
    rows: Sequence[dict[str, Any]], as_of: str | None
) -> dict[str, Any] | None:
    sorted_rows = sorted(
        rows,
        key=lambda row: str(row.get("date", "")),
        reverse=True,
    )
    if as_of is None:
        return sorted_rows[0]
    for row in sorted_rows:
        if str(row.get("date", "")) <= as_of:
            return row
    return sorted_rows[-1]


def _linear_interp(pillars: list[tuple[float, float]], x: float) -> float:
    if x <= pillars[0][0]:
        return pillars[0][1]
    if x >= pillars[-1][0]:
        return pillars[-1][1]
    for (t0, r0), (t1, r1) in zip(pillars, pillars[1:]):
        if t0 <= x <= t1:
            if t1 == t0:
                return r0
            return r0 + (r1 - r0) * (x - t0) / (t1 - t0)
    return pillars[-1][1]


def _is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def dividend_yield_from_profile(
    profile: dict[str, Any] | None, *, spot: float
) -> tuple[float, str]:
    """Estimate a continuous dividend yield from FMP profile ``lastDividend``.

    Returns ``(q, note)``. ``q`` is a continuous annual yield estimated from
    the latest quarterly payment. ``note`` states the applied assumption or a
    human-readable reason when q defaulted to 0.
    """
    if not profile or spot <= 0:
        return 0.0, "未检测到股息（profile 或 spot 缺失）"
    raw = profile.get("lastDividend")
    if not _is_number(raw):
        return 0.0, "未检测到股息（lastDividend 缺失）"
    last_div = float(raw)
    if last_div <= 0:
        return 0.0, "未检测到股息（lastDividend <= 0）"
    annual_cash_yield = (last_div * 4.0) / spot
    return math.log1p(annual_cash_yield), "股息率按最近季度股息 × 4 年化估算"


# Symbol-level exercise style heuristic. Index-style underlyings trade European;
# most single-name equities and ETFs trade American. The UI exposes the choice
# so users can override when the heuristic is wrong.
_EUROPEAN_PREFIXES: tuple[str, ...] = ("SPX", "NDX", "RUT", "VIX", "VIX3M", "VVIX")
_EUROPEAN_NAMES: frozenset[str] = frozenset(_EUROPEAN_PREFIXES)


def infer_style(symbol: str) -> Style:
    sym = symbol.strip().upper()
    # I:SPX / I:VIX style prefixed by data vendors.
    bare = sym.split(":")[-1]
    if bare in _EUROPEAN_NAMES or sym.startswith("I:"):
        return "european"
    return "american"


def itm_call_dividend_warning(
    *, q: float, delta: float, dte: int, side: str
) -> str | None:
    """Return a warning string when early-exercise / dividend risk is material.

    Trigger: long calls with real dividend yield, deep ITM, short DTE — the
    one combination where the continuous-dividend CRR approximation diverges
    from the true discrete-dividend early-exercise value.
    """
    if side != "call" or q <= 0:
        return None
    if delta >= 0.8 and dte <= 45:
        return (
            "深度 ITM 美式 Call 且存在股息：当前连续股息率近似可能低估提前行权价值，"
            "建议结合实际除息日人工核对。"
        )
    return None



__all__ = [
    "FALLBACK_RATE",
    "interpolate_rate",
    "dividend_yield_from_profile",
    "infer_style",
    "itm_call_dividend_warning",
]
