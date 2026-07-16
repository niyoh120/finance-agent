"""Tests for the pricing core.

Covers:
- BSM against a public reference price (CBOE-style inputs).
- CRR convergence: European CRR -> BSM; American >= European.
- No-arbitrage bounds.
- IV round-trip across call/put, low/high vol, near-expiry.
- 0DTE / expired time-to-expiry semantics.
- Treasury interpolation + dividend-yield fallback + style inference.
"""

from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from options_dashboard.market_inputs import (
    FALLBACK_RATE,
    dividend_yield_from_profile,
    infer_style,
    interpolate_rate,
    itm_call_dividend_warning,
)
from options_dashboard.pricing import (
    DEFAULT_CRR_STEPS,
    SCENARIO_CRR_STEPS,
    bsm_greeks,
    bsm_price,
    crr_price,
    expiry_datetime,
    intrinsic_value,
    no_arb_bounds,
    solve_iv,
    years_to_expiry,
)

_NY = ZoneInfo("America/New_York")


# --------------------------------------------------------------------------- #
# BSM reference
# --------------------------------------------------------------------------- #

def test_bsm_known_price() -> None:
    # S=100, K=100, T=1y, sigma=0.20, r=0.05, q=0 -> European call ~10.4506.
    price = bsm_price(spot=100, strike=100, t=1.0, iv=0.20, r=0.05, q=0.0, side="call")
    assert price == pytest.approx(10.4506, abs=1e-3)


def test_bsm_put_call_parity() -> None:
    # C - P = S*e^{-qT} - K*e^{-rT}
    S, K, T, sigma, r, q = 120.0, 110.0, 0.75, 0.25, 0.04, 0.015
    c = bsm_price(spot=S, strike=K, t=T, iv=sigma, r=r, q=q, side="call")
    p = bsm_price(spot=S, strike=K, t=T, iv=sigma, r=r, q=q, side="put")
    parity = S * math.exp(-q * T) - K * math.exp(-r * T)
    assert (c - p) == pytest.approx(parity, abs=1e-6)


def test_bsm_greeks_signs() -> None:
    g_call = bsm_greeks(spot=100, strike=100, t=1.0, iv=0.2, r=0.05, q=0.0, side="call")
    g_put = bsm_greeks(spot=100, strike=100, t=1.0, iv=0.2, r=0.05, q=0.0, side="put")
    assert 0 < g_call["delta"] < 1
    assert -1 < g_put["delta"] < 0
    assert g_call["gamma"] == pytest.approx(g_put["gamma"], rel=1e-9)
    assert g_call["vega"] == pytest.approx(g_put["vega"], rel=1e-9)


# --------------------------------------------------------------------------- #
# CRR convergence & American features
# --------------------------------------------------------------------------- #

def test_crr_european_converges_to_bsm() -> None:
    S, K, T, sigma, r, q = 100.0, 105.0, 1.0, 0.25, 0.03, 0.01
    bsm = bsm_price(spot=S, strike=K, t=T, iv=sigma, r=r, q=q, side="put")
    for n in (100, 200, 400):
        eu = crr_price(spot=S, strike=K, t=T, iv=sigma, r=r, q=q, side="put",
                       steps=n, american=False)
        assert abs(eu - bsm) < 0.05  # within 5 cents at all three step counts
    # Higher step count should be at least as close.
    eu_hi = crr_price(spot=S, strike=K, t=T, iv=sigma, r=r, q=q, side="put",
                      steps=400, american=False)
    eu_lo = crr_price(spot=S, strike=K, t=T, iv=sigma, r=r, q=q, side="put",
                      steps=100, american=False)
    assert abs(eu_hi - bsm) <= abs(eu_lo - bsm) + 1e-6


def test_american_put_above_european_put() -> None:
    # Deep ITM put: American early-exercise premium should be non-negative.
    S, K, T, sigma, r, q = 70.0, 100.0, 0.5, 0.3, 0.05, 0.0
    am = crr_price(spot=S, strike=K, t=T, iv=sigma, r=r, q=q, side="put", american=True)
    eu = crr_price(spot=S, strike=K, t=T, iv=sigma, r=r, q=q, side="put", american=False)
    assert am >= eu - 1e-9


def test_price_within_no_arb_bounds() -> None:
    S, K, T, sigma, r, q = 100.0, 100.0, 0.25, 0.2, 0.04, 0.0
    lo, hi = no_arb_bounds(spot=S, strike=K, t=T, r=r, q=q, side="call")
    price = bsm_price(spot=S, strike=K, t=T, iv=sigma, r=r, q=q, side="call")
    assert lo - 1e-9 <= price <= hi + 1e-9


def test_crr_step_constants_are_sensible() -> None:
    assert SCENARIO_CRR_STEPS < DEFAULT_CRR_STEPS
    assert DEFAULT_CRR_STEPS == 200
    assert SCENARIO_CRR_STEPS == 100


# --------------------------------------------------------------------------- #
# IV round-trip
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("side", ["call", "put"])
@pytest.mark.parametrize("iv", [0.10, 0.30, 0.80])
def test_iv_round_trip_bsm(side: str, iv: float) -> None:
    S, K, T, r, q = 100.0, 100.0, 0.5, 0.04, 0.01
    price = bsm_price(spot=S, strike=K, t=T, iv=iv, r=r, q=q, side=side)
    res = solve_iv(price=price, spot=S, strike=K, t=T, r=r, q=q, side=side, style="european")
    assert res.status == "ok"
    assert res.iv == pytest.approx(iv, abs=1e-3)


def test_iv_round_trip_crr_american() -> None:
    S, K, T, r, q, iv = 95.0, 100.0, 0.4, 0.04, 0.0, 0.25
    price = crr_price(spot=S, strike=K, t=T, iv=iv, r=r, q=q, side="put", american=True)
    res = solve_iv(price=price, spot=S, strike=K, t=T, r=r, q=q, side="put", style="american")
    assert res.status == "ok"
    assert res.iv == pytest.approx(iv, abs=1e-2)


def test_iv_zero_price_returns_no_trade() -> None:
    res = solve_iv(price=0.0, spot=100, strike=100, t=0.5, r=0.04, q=0.0, side="call")
    assert res.status == "no_trade"
    assert res.iv is None


def test_iv_outside_bounds_detected() -> None:
    # Price > spot is impossible for a call.
    res = solve_iv(price=200.0, spot=100.0, strike=100.0, t=0.5, r=0.04, q=0.0, side="call")
    assert res.status == "outside_bounds"


# --------------------------------------------------------------------------- #
# 0DTE / time-to-expiry
# --------------------------------------------------------------------------- #

def test_years_to_expiry_past_clamps_to_zero() -> None:
    now = datetime(2026, 7, 14, 10, 0, tzinfo=_NY)
    past = datetime(2026, 7, 13, 16, 0, tzinfo=_NY)
    t, intraday = years_to_expiry(past, now=now)
    assert t == 0.0
    assert intraday is False


def test_years_to_expiry_intraday_same_day() -> None:
    now = datetime(2026, 7, 14, 12, 0, tzinfo=_NY)
    expiry = datetime(2026, 7, 14, 16, 0, tzinfo=_NY)
    t, intraday = years_to_expiry(expiry, now=now)
    assert intraday is True
    assert t == pytest.approx(4.0 / (365 * 24), rel=1e-6)


def test_years_to_expiry_after_close_returns_zero() -> None:
    # Same-day but already past 16:00 -> expiry reached.
    now = datetime(2026, 7, 14, 16, 30, tzinfo=_NY)
    expiry = datetime(2026, 7, 14, 16, 0, tzinfo=_NY)
    t, intraday = years_to_expiry(expiry, now=now)
    assert t == 0.0
    assert intraday is False


def test_expiry_datetime_parses_occ_date() -> None:
    dt = expiry_datetime("2026-07-17")
    assert dt.tzinfo is not None
    # 16:00 NY close on the expiry date.
    assert dt.hour == 16


def test_intrinsic_value_helpers() -> None:
    assert intrinsic_value(110, 100, "call") == 10
    assert intrinsic_value(90, 100, "put") == 10
    assert intrinsic_value(90, 100, "call") == 0


# --------------------------------------------------------------------------- #
# Market inputs
# --------------------------------------------------------------------------- #

def test_treasury_interpolation_mid_pillar() -> None:
    rows = [{"date": "2026-07-10", "month3": 4.0, "month6": 4.2}]
    rate, source = interpolate_rate(rows, tenor_years=4 / 12)
    assert rate == pytest.approx(0.0406666, abs=1e-5)
    assert source == "treasury-interp"


def test_treasury_interpolation_clamps() -> None:
    rows = [{"date": "2026-07-10", "month1": 4.0, "year30": 5.0}]
    rate_low, _ = interpolate_rate(rows, tenor_years=0.001)
    rate_high, _ = interpolate_rate(rows, tenor_years=100.0)
    assert rate_low == pytest.approx(0.04)
    assert rate_high == pytest.approx(0.05)


def test_treasury_interpolation_fallback_on_empty() -> None:
    rate, source = interpolate_rate([], tenor_years=1.0)
    assert rate == FALLBACK_RATE
    assert "fallback" in source


def test_dividend_yield_from_profile_variants() -> None:
    q, note = dividend_yield_from_profile({"lastDividend": 2.0}, spot=100.0)
    assert q == pytest.approx(math.log1p(0.08))
    assert "× 4" in note
    assert dividend_yield_from_profile({"lastDividend": 0}, spot=100.0)[0] == 0.0
    assert dividend_yield_from_profile({"lastDividend": None}, spot=100.0)[0] == 0.0
    assert dividend_yield_from_profile(None, spot=100.0)[0] == 0.0


def test_infer_style_known_symbols() -> None:
    assert infer_style("SPX") == "european"
    assert infer_style("I:VIX") == "european"
    assert infer_style("AAPL") == "american"
    assert infer_style("SPY") == "american"


def test_itm_call_dividend_warning_triggers() -> None:
    assert itm_call_dividend_warning(q=0.01, delta=0.9, dte=30, side="call") is not None
    assert itm_call_dividend_warning(q=0.0, delta=0.9, dte=30, side="call") is None
    assert itm_call_dividend_warning(q=0.01, delta=0.5, dte=30, side="call") is None
    assert itm_call_dividend_warning(q=0.01, delta=0.9, dte=30, side="put") is None
