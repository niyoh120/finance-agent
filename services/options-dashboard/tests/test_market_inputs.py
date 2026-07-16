"""Market input normalization tests."""

from __future__ import annotations

import math

import pytest
from options_dashboard.market_inputs import dividend_yield_from_profile, interpolate_rate


def test_interpolate_rate_sorts_unordered_treasury_rows() -> None:
    rows = [
        {"date": "2026-01-01", "month1": 1.0},
        {"date": "2026-02-01", "month1": 5.0},
    ]

    latest, _ = interpolate_rate(rows, tenor_years=1 / 12)
    historical, _ = interpolate_rate(rows, tenor_years=1 / 12, as_of="2026-01-15")

    assert latest == pytest.approx(0.05)
    assert historical == pytest.approx(0.01)


def test_dividend_yield_annualizes_latest_quarterly_payment() -> None:
    q, note = dividend_yield_from_profile({"lastDividend": 1.0}, spot=100.0)

    assert q == pytest.approx(math.log1p(0.04))
    assert "× 4" in note
