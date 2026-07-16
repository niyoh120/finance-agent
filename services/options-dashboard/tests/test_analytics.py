"""Earnings IV Crush analytics tests."""

from __future__ import annotations

from datetime import date

import pytest
from options_dashboard.analytics import (
    EarningsCrushSample,
    EarningsEvent,
    build_option_symbol,
    nearest_option_expiration,
    parse_earnings_rows,
    summarize_crush,
    underlying_gap_pct,
)


def test_build_option_symbol() -> None:
    assert build_option_symbol(
        "AAPL", date(2026, 9, 18), "call", 100.0
    ) == "O:AAPL260918C00100000"
    assert build_option_symbol(
        "SPY", date(2026, 1, 17), "put", 450.5
    ) == "O:SPY260117P00450500"


def test_third_friday_basic() -> None:
    assert nearest_option_expiration(date(2026, 1, 1)) == date(2026, 1, 16)
    assert nearest_option_expiration(date(2026, 1, 16)) == date(2026, 1, 16)
    assert nearest_option_expiration(date(2026, 1, 17)) == date(2026, 2, 20)


def test_parse_earnings_rows_normalizes() -> None:
    rows = [
        {
            "date": "2026-01-29",
            "epsActual": 2.85,
            "epsEstimated": 2.67,
            "revenueActual": 143756000000,
            "revenueEstimated": 138391000000,
        },
    ]
    events = parse_earnings_rows(rows)
    assert events[0].date == date(2026, 1, 29)
    assert events[0].eps_actual == 2.85


def test_underlying_gap_pct_direction() -> None:
    closes = [
        (date(2026, 1, 28), 270.0),
        (date(2026, 1, 29), 271.1),
        (date(2026, 1, 30), 275.0),
    ]
    gap = underlying_gap_pct(closes, event_date=date(2026, 1, 29))
    assert gap == pytest.approx((275.0 - 270.0) / 270.0)


def test_summarize_crush_counts_only_complete_samples() -> None:
    event = EarningsEvent(date(2026, 1, 29), None, None, None, None)
    samples = [
        EarningsCrushSample(event, 0.4, 0.3, 0.25, 0.02, "good"),
        EarningsCrushSample(event, None, None, None, 0.03, "no_trade"),
        EarningsCrushSample(event, 0.4, None, None, None, "no_trade"),
    ]

    summary = summarize_crush(samples)

    assert summary.sample_count == 1
    assert "< 4" in summary.confidence_note


def test_summarize_crush_median_and_percentiles() -> None:
    samples = [
        EarningsCrushSample(
            EarningsEvent(date(2026, 1, 29), None, None, None, None),
            0.4,
            0.3,
            0.25,
            0.02,
            "good",
        ),
    ] * 6
    summary = summarize_crush(samples)
    assert summary.sample_count == 6
    assert summary.median_crush_pct == pytest.approx(0.25)
    assert summary.median_gap_pct == pytest.approx(0.02)
