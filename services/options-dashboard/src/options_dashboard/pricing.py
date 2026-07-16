"""Option pricing, Greeks and implied-volatility solving.

Two pricing engines live here:

- :func:`bsm_price` / :func:`bsm_greeks` — closed-form Black–Scholes–Merton for
  European options (used for index options like SPX/VIX/NDX/RUT and as the
  benchmark that CRR must converge to in tests).
- :func:`crr_price` / :func:`crr_greeks` — Cox–Ross–Rubinstein binomial tree
  that supports American exercise and continuous dividend yield, used for
  stock/ETF options.

IV is solved by bisection with no-arbitrage bounds checking. Time-to-expiry is
computed in business-day precision; the 0DTE path computes intraday remaining
hours under ``America/New_York`` regular session hours and falls back to
intrinsic-only valuation when the market is closed or the option has expired.

Inputs are kept intentionally narrow (spot/strike/T/iv/r/q/cp/style); market
data adapters (Treasury interpolation, dividend estimation from profile) live
in :mod:`options_dashboard.market_inputs`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

# Type aliases kept narrow so the pricing core never imports Streamlit or the
# ConvexValue client.
Side = Literal["call", "put"]
Style = Literal["european", "american"]

_SQRT_2PI = math.sqrt(2.0 * math.pi)
_NEW_YORK = ZoneInfo("America/New_York")
_REGULAR_OPEN = time(9, 30)
_REGULAR_CLOSE = time(16, 0)

# CRR step counts. Single-point pricing uses 200 steps for accuracy; the
# interactive scenario grid uses 100 to keep multi-leg revaluation responsive.
# Both are module constants so tests and the UI reference the same source.
DEFAULT_CRR_STEPS = 200
SCENARIO_CRR_STEPS = 100

# IV solver bounds. Below ~1e-4 annualized vol or above ~5.0 the price is
# either effectively zero or dominated by numerical noise; clamp there.
_IV_MIN = 1e-4
_IV_MAX = 5.0
_IV_TOL = 1e-4
_IV_MAX_ITER = 80

# 365-day convention for T (calendar time). Options price on calendar days,
# not trading days; exchange calendars matter for early-exercise decisions at
# the microstructure level, which is out of scope for this MVP.
_DAYS_PER_YEAR = 365.0


# --------------------------------------------------------------------------- #
# Normal CDF (pure stdlib)
# --------------------------------------------------------------------------- #

def _norm_cdf(x: float) -> float:
    # Abramowitz & Stegun 26.2.17 — max abs error ~7.5e-8, ample for pricing.
    if x < 0:
        return 1.0 - _norm_cdf(-x)
    k = 1.0 / (1.0 + 0.2316419 * x)
    a1, a2, a3, a4, a5 = (
        0.319381530,
        -0.356563782,
        1.781477937,
        -1.821255978,
        1.330274429,
    )
    poly = ((((a5 * k + a4) * k + a3) * k + a2) * k + a1) * k
    return 1.0 - math.exp(-x * x / 2.0) / _SQRT_2PI * poly


def _norm_pdf(x: float) -> float:
    return math.exp(-x * x / 2.0) / _SQRT_2PI


# --------------------------------------------------------------------------- #
# Black–Scholes–Merton
# --------------------------------------------------------------------------- #

def bsm_price(
    *,
    spot: float,
    strike: float,
    t: float,
    iv: float,
    r: float,
    q: float,
    side: Side,
) -> float:
    """European option price (Black–Scholes–Merton with continuous dividend ``q``)."""
    if t <= 0:
        return _intrinsic(spot, strike, side)
    if iv <= 0:
        # Zero vol -> deterministic forward; price = discounted intrinsic of forward.
        fwd = spot * math.exp((r - q) * t)
        return math.exp(-r * t) * max(0.0, fwd - strike if side == "call" else strike - fwd)
    sqrt_t = math.sqrt(t)
    d1 = (math.log(spot / strike) + (r - q + 0.5 * iv * iv) * t) / (iv * sqrt_t)
    d2 = d1 - iv * sqrt_t
    disc = math.exp(-r * t)
    if side == "call":
        return spot * math.exp(-q * t) * _norm_cdf(d1) - strike * disc * _norm_cdf(d2)
    return strike * disc * _norm_cdf(-d2) - spot * math.exp(-q * t) * _norm_cdf(-d1)


def bsm_greeks(
    *,
    spot: float,
    strike: float,
    t: float,
    iv: float,
    r: float,
    q: float,
    side: Side,
) -> dict[str, float]:
    """Full Greek set for a European option.

    Theta is per-day (divided by 365), matching how traders read it. Rho is
    per-1%-vol (divided by 100) for the same reason.
    """
    greeks = {k: 0.0 for k in ("delta", "gamma", "theta", "vega", "rho")}
    if t <= 0 or iv <= 0:
        greeks["delta"] = _bsm_intrinsic_delta(spot, strike, side)
        return greeks
    sqrt_t = math.sqrt(t)
    d1 = (math.log(spot / strike) + (r - q + 0.5 * iv * iv) * t) / (iv * sqrt_t)
    d2 = d1 - iv * sqrt_t
    disc = math.exp(-r * t)
    q_disc = math.exp(-q * t)
    pdf_d1 = _norm_pdf(d1)
    sign = 1.0 if side == "call" else -1.0
    greeks["delta"] = sign * q_disc * _norm_cdf(sign * d1)
    greeks["gamma"] = pdf_d1 * q_disc / (spot * iv * sqrt_t)
    # Per-day theta.
    term1 = -(spot * q_disc * pdf_d1 * iv) / (2.0 * sqrt_t)
    if side == "call":
        theta_daily = (
            term1 - r * strike * disc * _norm_cdf(d2) + q * spot * q_disc * _norm_cdf(d1)
        ) / _DAYS_PER_YEAR
        greeks["rho"] = strike * t * disc * _norm_cdf(d2) / 100.0
    else:
        theta_daily = (
            term1 + r * strike * disc * _norm_cdf(-d2) - q * spot * q_disc * _norm_cdf(-d1)
        ) / _DAYS_PER_YEAR
        greeks["rho"] = -strike * t * disc * _norm_cdf(-d2) / 100.0
    greeks["theta"] = theta_daily
    # Vega is the same for call/put; scale to per-1%-vol.
    greeks["vega"] = spot * q_disc * pdf_d1 * sqrt_t / 100.0
    return greeks


def _bsm_intrinsic_delta(spot: float, strike: float, side: Side) -> float:
    if side == "call":
        return 1.0 if spot > strike else (0.5 if spot == strike else 0.0)
    return -1.0 if spot < strike else (-0.5 if spot == strike else 0.0)


# --------------------------------------------------------------------------- #
# Cox–Ross–Rubinstein binomial tree
# --------------------------------------------------------------------------- #

def crr_price(
    *,
    spot: float,
    strike: float,
    t: float,
    iv: float,
    r: float,
    q: float,
    side: Side,
    steps: int = DEFAULT_CRR_STEPS,
    american: bool = True,
) -> float:
    """CRR binomial price.

    Supports European (``american=False``) and American exercise. The European
    branch must converge to :func:`bsm_price`; that equivalence is asserted in
    tests. Continuous dividend yield ``q`` is built into the risk-neutral
    growth factor.
    """
    if t <= 0:
        return _intrinsic(spot, strike, side)
    if iv <= 0:
        return bsm_price(spot=spot, strike=strike, t=t, iv=iv, r=r, q=q, side=side)
    n = max(1, int(steps))
    dt = t / n
    up = math.exp(iv * math.sqrt(dt))
    down = 1.0 / up
    # Risk-neutral prob of up move. q enters as a drag on growth.
    growth = math.exp((r - q) * dt)
    p_up = (growth - down) / (up - down)
    if not (0.0 < p_up < 1.0):
        # No arbitrage violated at this step size: degenerate to forward intrinsic.
        return max(_intrinsic(spot, strike, side), bsm_price(
            spot=spot, strike=strike, t=t, iv=max(iv, 1e-6), r=r, q=q, side=side
        ))
    disc = math.exp(-r * dt)
    # Terminal payoffs at step n.
    prices = [spot * (up ** (n - j)) * (down ** j) for j in range(n + 1)]
    values = [
        max(0.0, (1.0 if side == "call" else -1.0) * (price - strike))
        for price in prices
    ]

    # Backward induction.
    for i in range(n - 1, -1, -1):
        for j in range(i + 1):
            s = spot * (up ** (i - j)) * (down ** j)
            cont = disc * (p_up * values[j] + (1.0 - p_up) * values[j + 1])
            if american:
                exercise = max(0.0, (1.0 if side == "call" else -1.0) * (s - strike))
                values[j] = max(cont, exercise)
            else:
                values[j] = cont
    return values[0]


def crr_greeks(
    *,
    spot: float,
    strike: float,
    t: float,
    iv: float,
    r: float,
    q: float,
    side: Side,
    steps: int = DEFAULT_CRR_STEPS,
    american: bool = True,
) -> dict[str, float]:
    """American Greeks via bump-and-revalue on the CRR tree.

    Delta/gamma use spot bumps; vega uses vol bumps; theta uses a one-day
    horizon shift. This mirrors how traders read these off a model and avoids
    the fragility of closed-form tree Greeks for American options.
    """
    out = {k: 0.0 for k in ("delta", "gamma", "theta", "vega", "rho")}
    if t <= 0 or iv <= 0:
        out["delta"] = _bsm_intrinsic_delta(spot, strike, side)
        return out

    base = crr_price(spot=spot, strike=strike, t=t, iv=iv, r=r, q=q, side=side,
                     steps=steps, american=american)
    h_s = max(spot * 1e-3, 1e-4)
    up_price = crr_price(spot=spot + h_s, strike=strike, t=t, iv=iv, r=r, q=q,
                         side=side, steps=steps, american=american)
    dn_price = crr_price(spot=spot - h_s, strike=strike, t=t, iv=iv, r=r, q=q,
                         side=side, steps=steps, american=american)
    delta = (up_price - dn_price) / (2.0 * h_s)
    gamma = (up_price - 2.0 * base + dn_price) / (h_s * h_s) if h_s > 0 else 0.0

    h_v = max(iv * 1e-2, 1e-4)
    v_up = crr_price(spot=spot, strike=strike, t=t, iv=iv + h_v, r=r, q=q,
                     side=side, steps=steps, american=american)
    v_dn = crr_price(spot=spot, strike=strike, t=t, iv=iv - h_v if iv - h_v > 0 else 1e-4,
                     r=r, q=q, side=side, steps=steps, american=american)
    vega = (v_up - v_dn) / (2.0 * h_v) / 100.0

    # Theta: reprice with T shrunk by one calendar day.
    t_minus_day = max(t - 1.0 / _DAYS_PER_YEAR, 1e-6)
    t_next = crr_price(spot=spot, strike=strike, t=t_minus_day, iv=iv, r=r, q=q,
                       side=side, steps=steps, american=american)
    theta = (t_next - base)  # per-day (one-day-forward minus today)

    out.update({"delta": delta, "gamma": gamma, "theta": theta, "vega": vega})
    return out


# --------------------------------------------------------------------------- #
# Unified pricing entry points
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class OptionResult:
    price: float
    greeks: dict[str, float]
    style: Style
    model: str  # "bsm" | "crr"


def price_option(
    *,
    spot: float,
    strike: float,
    t: float,
    iv: float,
    r: float,
    q: float,
    side: Side,
    style: Style = "american",
    steps: int = DEFAULT_CRR_STEPS,
) -> OptionResult:
    """Price an option with the engine selected by ``style``."""
    if style == "european":
        price = bsm_price(spot=spot, strike=strike, t=t, iv=iv, r=r, q=q, side=side)
        greeks = bsm_greeks(spot=spot, strike=strike, t=t, iv=iv, r=r, q=q, side=side)
        return OptionResult(price=price, greeks=greeks, style="european", model="bsm")
    price = crr_price(spot=spot, strike=strike, t=t, iv=iv, r=r, q=q, side=side, steps=steps)
    greeks = crr_greeks(spot=spot, strike=strike, t=t, iv=iv, r=r, q=q, side=side, steps=steps)
    return OptionResult(price=price, greeks=greeks, style="american", model="crr")


# --------------------------------------------------------------------------- #
# Intrinsic / bounds helpers
# --------------------------------------------------------------------------- #

def _intrinsic(spot: float, strike: float, side: Side) -> float:
    if side == "call":
        return max(0.0, spot - strike)
    return max(0.0, strike - spot)


def intrinsic_value(spot: float, strike: float, side: Side) -> float:
    return _intrinsic(spot, strike, side)


def no_arb_bounds(
    *, spot: float, strike: float, t: float, r: float, q: float, side: Side
) -> tuple[float, float]:
    """Lower/upper no-arbitrage bounds for a vanilla option.

    Used by the IV solver to reject market prices that cannot come from any
    positive volatility (stale prints, data errors).
    """
    disc = math.exp(-r * t) if t > 0 else 1.0
    q_disc = math.exp(-q * t) if t > 0 else 1.0
    if side == "call":
        lower = max(0.0, spot * q_disc - strike * disc)
        upper = spot * q_disc
    else:
        lower = max(0.0, strike * disc - spot * q_disc)
        upper = strike * disc
    return lower, upper


# --------------------------------------------------------------------------- #
# Implied volatility solver
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class IVResult:
    iv: float | None
    status: str  # "ok" | "no_trade" | "outside_bounds" | "no_convergence"
    iterations: int


def solve_iv(
    *,
    price: float,
    spot: float,
    strike: float,
    t: float,
    r: float,
    q: float,
    side: Side,
    style: Style = "american",
    steps: int = SCENARIO_CRR_STEPS,
) -> IVResult:
    """Solve for implied volatility by bisection.

    Bisection (not Newton) is deliberate: the CRR price-vol relationship has
    no clean analytic derivative, and bisection stays robust near zero vol and
    deep ITM/OTM where Newton oscillates.
    """
    if price <= 0:
        return IVResult(iv=None, status="no_trade", iterations=0)

    lower, upper_bound = no_arb_bounds(
        spot=spot, strike=strike, t=t, r=r, q=q, side=side
    )
    if not (lower - 1e-9 <= price <= upper_bound + 1e-9):
        return IVResult(iv=None, status="outside_bounds", iterations=0)

    def model(iv: float) -> float:
        if style == "european":
            return bsm_price(spot=spot, strike=strike, t=t, iv=iv, r=r, q=q, side=side)
        return crr_price(spot=spot, strike=strike, t=t, iv=iv, r=r, q=q,
                         side=side, steps=steps)

    lo, hi = _IV_MIN, _IV_MAX
    p_lo = model(lo)
    p_hi = model(hi)
    # If price is outside the model's achievable range at the vol bounds, bail.
    if price < p_lo - 1e-6 or price > p_hi + 1e-6:
        return IVResult(iv=None, status="outside_bounds", iterations=0)

    it = 0
    mid = 0.0
    for it in range(1, _IV_MAX_ITER + 1):
        mid = 0.5 * (lo + hi)
        p_mid = model(mid)
        if abs(p_mid - price) < _IV_TOL:
            return IVResult(iv=mid, status="ok", iterations=it)
        if p_mid < price:
            lo = mid
        else:
            hi = mid
    return IVResult(iv=mid, status="no_convergence", iterations=it)


# --------------------------------------------------------------------------- #
# Time-to-expiry (calendar + 0DTE intraday)
# --------------------------------------------------------------------------- #

def years_to_expiry(
    expiry: datetime, *, now: datetime | None = None
) -> tuple[float, bool]:
    """Calendar years from *now* to *expiry*.

    Returns ``(T, is_intraday)``. ``is_intraday`` is True when expiry is today
    and the regular session is still open; callers use it to warn about 0DTE
    time-sensitivity. After close, T is clamped to 0 so pricing collapses to
    intrinsic.
    """
    ref = now or datetime.now(tz=_NEW_YORK)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=_NEW_YORK)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=_NEW_YORK)

    if expiry <= ref:
        return 0.0, False

    same_day = expiry.date() == ref.date()
    if same_day:
        # 0DTE: only count hours remaining in today's regular session.
        session_close = datetime.combine(ref.date(), _REGULAR_CLOSE, tzinfo=_NEW_YORK)
        if ref.time() < _REGULAR_OPEN:
            ref = datetime.combine(ref.date(), _REGULAR_OPEN, tzinfo=_NEW_YORK)
        remaining = (min(expiry, session_close) - ref).total_seconds()
        if remaining <= 0:
            return 0.0, False
        return remaining / (_DAYS_PER_YEAR * 24 * 3600), True

    seconds = (expiry - ref).total_seconds()
    return seconds / (_DAYS_PER_YEAR * 24 * 3600), False


def expiry_datetime(date_str: str) -> datetime:
    """Parse an OCC-style expiration date (YYYY-MM-DD) as 16:00 NY time."""
    from datetime import date as _date

    d = _date.fromisoformat(str(date_str)[:10])
    return datetime.combine(d, _REGULAR_CLOSE, tzinfo=_NEW_YORK)


__all__ = [
    "DEFAULT_CRR_STEPS",
    "SCENARIO_CRR_STEPS",
    "OptionResult",
    "IVResult",
    "bsm_price",
    "bsm_greeks",
    "crr_price",
    "crr_greeks",
    "price_option",
    "intrinsic_value",
    "no_arb_bounds",
    "solve_iv",
    "years_to_expiry",
    "expiry_datetime",
]
