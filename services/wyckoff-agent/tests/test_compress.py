from datetime import UTC, datetime

from wyckoff_agent.compress import extract_pivots
from wyckoff_agent.schemas import Candle


def test_extract_pivots_limits_max_pivots():
    candles = []
    t0 = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp())

    # Create a synthetic sawtooth series
    for i in range(20000):
        price = 100.0 + (i % 50) * 0.1
        candles.append(
            Candle(
                time=t0 + i * 60,
                timestamp=(t0 + i * 60) * 1000,
                open=price,
                high=price + 0.05,
                low=price - 0.05,
                close=price,
                volume=100.0,
            )
        )

    result = extract_pivots(candles=candles, min_swing_pct=0.001, max_pivots=300)
    assert len(result.pivots) <= 300
