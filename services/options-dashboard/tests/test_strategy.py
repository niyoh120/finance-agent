"""Strategy module tests.

Covers:
- Leg sign conventions and stock-leg delta.
- Net Greeks aggregation direction (long vs short).
- Single-expiry terminal payoff: breakevens, max profit/loss for debit spread,
  straddle, iron condor, stock+option (covered call).
- Multi-expiry payoff is rejected.
- Suggested limit price direction (buy vs sell), sparse-anchor guard,
  0DTE/low-volume confidence downgrade.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from options_dashboard.strategy import (
    Leg,
    MixedExpiryError,
    PricingContext,
    current_payoff_curve,
    suggest_limit_price,
    template_bull_call_spread,
    template_iron_condor,
    template_straddle,
    terminal_payoff,
    value_strategy,
)


def test_stock_leg_sign_and_delta() -> None:
    leg = Leg("stock", "buy", 100, "AAPL", cost=200.0)
    assert leg.signed_quantity() == 100
    ctx = PricingContext(spot=210.0, r=0.04, q=0.0)
    val = value_strategy([leg], ctx)
    assert val.legs[0].price == 210.0
    assert val.legs[0].greeks["delta"] == 1.0
    # Mark-to-model P&L = (210 - 200) * 100 = 1000.
    assert val.unrealized == pytest.approx(1000.0)


def test_short_option_negates_greeks() -> None:
    ctx = PricingContext(spot=100.0, r=0.04, q=0.0, default_iv=0.3)
    long_call = Leg("option", "buy", 1, "AAPL", strike=100.0,
                    expiration=date(2026, 9, 18), option_side="call", cost=5.0)
    short_call = Leg("option", "sell", 1, "AAPL", strike=100.0,
                     expiration=date(2026, 9, 18), option_side="call", cost=5.0)
    both = value_strategy([long_call, short_call], ctx)
    # Delta should cancel out.
    assert both.net_greeks["delta"] == pytest.approx(0.0, abs=1e-9)


def test_bull_call_spread_bounded_payoff() -> None:
    expiration = date(2026, 9, 18)
    legs = template_bull_call_spread(
        "AAPL", long_strike=100.0, short_strike=110.0, expiration=expiration,
        long_cost=5.0, short_cost=2.0,
    )
    payoff = terminal_payoff(legs)
    # Max profit = (110-100) - net debit (5-2) = 7.
    assert payoff.max_profit == pytest.approx(7.0, abs=0.05)
    # Max loss = net debit = 3.
    assert payoff.max_loss == pytest.approx(3.0, abs=0.05)
    # One breakeven near 103.
    assert any(abs(b - 103.0) < 0.5 for b in payoff.breakevens)


def test_long_straddle_two_breakevens() -> None:
    expiration = date(2026, 9, 18)
    legs = template_straddle(
        "AAPL", strike=100.0, expiration=expiration, call_cost=5.0, put_cost=5.0
    )
    payoff = terminal_payoff(legs)
    assert len(payoff.breakevens) >= 2
    assert payoff.max_loss == pytest.approx(10.0, abs=0.05)  # total premium


def test_iron_condor_bounded() -> None:
    expiration = date(2026, 9, 18)
    legs = template_iron_condor(
        "AAPL", expiration,
        put_long=85.0, put_short=90.0, call_short=110.0, call_long=115.0,
        put_long_cost=0.5, put_short_cost=1.0,
        call_short_cost=1.0, call_long_cost=0.5,
    )
    payoff = terminal_payoff(legs)
    # Both max profit and max loss should be finite for an iron condor.
    assert payoff.max_profit is not None
    assert payoff.max_loss is not None
    # Net credit = (1.0 + 1.0) - (0.5 + 0.5) = 1.0 -> max profit near credit.
    assert payoff.max_profit == pytest.approx(1.0, abs=0.05)


def test_covered_call_stock_plus_option() -> None:
    expiration = date(2026, 9, 18)
    stock = Leg("stock", "buy", 100, "AAPL", cost=200.0)
    short_call = Leg("option", "sell", 1, "AAPL", strike=210.0,
                     expiration=expiration, option_side="call", cost=3.0)
    payoff = terminal_payoff([stock, short_call])
    # At very high prices the stock keeps making money, so payoff is not capped
    # from above (max_profit finite at scan boundary, but strategy is bullish).
    assert payoff.max_loss is not None  # downside is bounded by stock cost - premium


def test_multi_expiry_rejected() -> None:
    a = Leg("option", "buy", 1, "AAPL", strike=100.0,
            expiration=date(2026, 9, 18), option_side="call", cost=5.0)
    b = Leg("option", "buy", 1, "AAPL", strike=100.0,
            expiration=date(2026, 10, 16), option_side="call", cost=5.0)
    with pytest.raises(MixedExpiryError):
        terminal_payoff([a, b])


# ---------- suggested limit price ----------

def test_suggest_limit_price_buy_direction() -> None:
    s = suggest_limit_price(
        fmv=5.0, model_price=5.2, day_vwap=5.1, day_close=5.15,
        open_interest=500, volume=200,
    )
    directional = s.as_directional("buy")
    assert directional["conservative"] < directional["neutral"] < directional["aggressive"]


def test_suggest_limit_price_sell_direction_reversed() -> None:
    s = suggest_limit_price(
        fmv=5.0, model_price=5.2, day_vwap=5.1, day_close=5.15,
        open_interest=500, volume=200,
    )
    directional = s.as_directional("sell")
    keys = list(directional)
    # Seller wants higher price first.
    assert directional[keys[0]] >= directional[keys[-1]]


def test_suggest_limit_price_sparse_anchors_returns_none_tiers() -> None:
    s = suggest_limit_price(
        fmv=None, model_price=5.0, day_vwap=None, day_close=None,
        open_interest=None, volume=None,
    )
    assert s.conservative is None
    assert s.neutral is None
    assert s.aggressive is None
    assert s.confidence == "low"


def test_suggest_limit_price_0dte_forces_low_confidence() -> None:
    s = suggest_limit_price(
        fmv=5.0, model_price=5.1, day_vwap=5.05, day_close=5.05,
        open_interest=1000, volume=500, is_0dte=True,
    )
    assert s.confidence == "low"
    # Tiers may still be returned, but note must flag the caveat.
    assert "0DTE" in s.note


# ---------- current_payoff_curve ----------

def test_current_payoff_curve_long_call_shape() -> None:
    """Long call: expiry PnL is flat-then-linear; current PnL is curved above."""
    leg = Leg("option", "buy", 1, "AAPL", strike=100.0,
              expiration=date(2026, 9, 18), option_side="call", cost=5.0)
    ctx = PricingContext(spot=100.0, r=0.04, q=0.0, default_iv=0.3)
    curves = current_payoff_curve([leg], ctx=ctx)
    assert len(curves.xs) == len(curves.expiry_points) == len(curves.current_points)
    # Expiry PnL at very low price = -cost (max loss).
    assert curves.expiry_points[0] == pytest.approx(-5.0, abs=0.01)
    # Expiry PnL at very high price = positive (unlimited upside).
    assert curves.expiry_points[-1] > 0
    # Current PnL at spot should be near zero (model price ≈ cost at entry).
    mid = len(curves.xs) // 2
    assert curves.current_points[mid] > curves.expiry_points[mid]  # time value


def test_current_payoff_curve_uses_per_leg_iv_overrides() -> None:
    """Per-leg IV keeps current PnL distinct from intrinsic expiry PnL."""
    leg = Leg(
        "option",
        "buy",
        1,
        "O:AAPL260918C00100000",
        strike=100.0,
        expiration=date(2026, 9, 18),
        option_side="call",
        cost=5.0,
    )
    ctx = PricingContext(
        spot=100.0,
        r=0.04,
        q=0.0,
        default_iv=None,
        now=datetime(2026, 7, 15, 12, 0),
    )
    curves = current_payoff_curve(
        [leg],
        ctx=ctx,
        iv_overrides={leg.kind_symbol: 0.3},
        spot_range=(95.0, 105.0),
        samples=11,
    )

    at_the_money = 5
    assert curves.current_points[at_the_money] > curves.expiry_points[at_the_money]


def test_naked_short_call_has_bounded_profit_and_unbounded_loss() -> None:
    expiration = date(2026, 9, 18)
    leg = Leg(
        "option",
        "sell",
        1,
        "AAPL",
        strike=100.0,
        expiration=expiration,
        option_side="call",
        cost=5.0,
    )

    payoff = terminal_payoff([leg])

    assert payoff.max_profit == pytest.approx(5.0, abs=0.05)
    assert payoff.max_loss is None


def test_partially_covered_short_calls_keep_unbounded_loss() -> None:
    expiration = date(2026, 9, 18)
    legs = [
        Leg("stock", "buy", 100, "AAPL", cost=100.0),
        Leg(
            "option",
            "sell",
            2,
            "AAPL",
            strike=100.0,
            expiration=expiration,
            option_side="call",
            cost=5.0,
        ),
    ]

    payoff = terminal_payoff(legs)

    assert payoff.max_loss is None


def test_missing_cost_uses_same_expiry_payoff_in_both_curves() -> None:
    expiration = date(2026, 9, 18)
    legs = [
        Leg("stock", "buy", 1, "AAPL"),
        Leg(
            "option",
            "buy",
            1,
            "AAPL",
            strike=100.0,
            expiration=expiration,
            option_side="call",
        ),
    ]
    ctx = PricingContext(spot=100.0, r=0.04, q=0.0, default_iv=0.3)
    terminal = terminal_payoff(legs, spot_range=(95.0, 105.0), samples=3)
    curves = current_payoff_curve(
        legs,
        ctx=ctx,
        spot_range=(95.0, 105.0),
        samples=3,
    )

    assert [pnl for _, pnl in terminal.points] == pytest.approx(curves.expiry_points)


def test_current_payoff_curve_bull_spread_no_negative_expiry() -> None:
    """Bull call spread: expiry PnL bounded between -net_debit and +max_profit."""
    expiration = date(2026, 9, 18)
    legs = [
        Leg("option", "buy", 1, "AAPL", strike=100.0, expiration=expiration,
            option_side="call", cost=5.0),
        Leg("option", "sell", 1, "AAPL", strike=110.0, expiration=expiration,
            option_side="call", cost=2.0),
    ]
    ctx = PricingContext(spot=100.0, r=0.04, q=0.0, default_iv=0.3)
    curves = current_payoff_curve(legs, ctx=ctx)
    # Max loss (at very low price) = -net debit = -(5-2) = -3.
    assert curves.expiry_points[0] == pytest.approx(-3.0, abs=0.01)
    # Max profit (at very high price) = (110-100) - 3 = 7.
    assert curves.expiry_points[-1] == pytest.approx(7.0, abs=0.05)
