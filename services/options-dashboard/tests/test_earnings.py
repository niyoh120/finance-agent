"""Focused tests for earnings IV-crush strategy valuation."""

from __future__ import annotations

from datetime import date, datetime

import options_dashboard.data as data_mod
import options_dashboard.pages.earnings as earnings_mod
import pytest
from options_dashboard.analytics import EarningsEvent
from options_dashboard.pages.earnings import value_earnings_crush_scenario
from options_dashboard.strategy import Leg, PricingContext


def _long_call() -> Leg:
    return Leg(
        "option",
        "buy",
        1,
        "O:AAPL260918C00100000",
        strike=100.0,
        expiration=date(2026, 9, 18),
        option_side="call",
        cost=5.0,
    )


def test_earnings_crush_reprices_strategy_after_event() -> None:
    """A long call loses value when IV drops and spot stays unchanged."""
    leg = _long_call()
    ctx = PricingContext(
        spot=100.0,
        r=0.04,
        q=0.0,
        now=datetime(2026, 7, 20, 12, 0),
    )

    before, after, post_spot = value_earnings_crush_scenario(
        [leg],
        ctx,
        {leg.kind_symbol: 0.30},
        event_date=date(2026, 7, 17),
        gap_pct=0.0,
        crush_pct=-0.20,
    )

    assert post_spot == 100.0
    assert after.net_price < before.net_price


def test_analyze_event_skips_malformed_equity_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        data_mod,
        "fetch_equity_eod_sync",
        lambda *_: [
            {"date": "bad-date", "close": "bad-close"},
            {"date": "2026-01-16", "close": 100.0},
        ],
    )
    monkeypatch.setattr(data_mod, "fetch_treasury_rates_sync", lambda **_: [])
    monkeypatch.setattr(data_mod, "fetch_option_daily_sync", lambda *_: {"close": 5.0})

    sample = earnings_mod._analyze_event(
        "AAPL",
        EarningsEvent(date(2026, 1, 17), None, None, None, None),
        "american",
        0.0,
        100.0,
    )

    assert sample is not None
    assert sample.underlying_gap_pct is None


def test_earnings_crush_requires_post_event_valuation_date() -> None:
    """There is no post-earnings valuation when the date has not passed."""
    leg = _long_call()
    ctx = PricingContext(
        spot=100.0,
        r=0.04,
        q=0.0,
        now=datetime(2026, 7, 17, 12, 0),
    )

    with pytest.raises(ValueError):
        value_earnings_crush_scenario(
            [leg],
            ctx,
            {leg.kind_symbol: 0.30},
            event_date=date(2026, 7, 17),
            gap_pct=0.0,
            crush_pct=-0.20,
        )
