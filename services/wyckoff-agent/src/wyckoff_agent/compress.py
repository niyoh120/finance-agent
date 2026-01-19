from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .schemas import Candle


@dataclass(frozen=True)
class PivotPoint:
    timestamp: datetime
    price: float
    kind: str  # "H" or "L"
    volume: float | None


@dataclass(frozen=True)
class CompressedSeries:
    pivots: list[PivotPoint]
    notes: str


def extract_pivots(
    *,
    candles: list[Candle],
    min_swing_pct: float = 0.003,
    max_pivots: int = 300,
) -> CompressedSeries:
    """A lightweight ZigZag-style pivot extractor.

    Goals:
    - Reduce 1m (<=14d) to <= max_pivots points.
    - Preserve major swings and extremes.

    This is intentionally simple and deterministic; later we can refine.
    """

    if len(candles) < 3:
        return CompressedSeries(pivots=[], notes="candles too short")

    pivots: list[PivotPoint] = []

    last_pivot_idx = 0
    last_pivot_price = candles[0].close
    direction: str | None = None  # "up" or "down"

    def pct(a: float, b: float) -> float:
        if b == 0:
            return 0.0
        return (a - b) / b

    for i in range(1, len(candles)):
        c = candles[i]
        move = pct(c.close, last_pivot_price)

        if direction is None:
            if abs(move) >= min_swing_pct:
                direction = "up" if move > 0 else "down"
            continue

        if direction == "up":
            # keep pushing higher
            if c.close >= candles[last_pivot_idx].close:
                last_pivot_idx = i
            # reversal
            elif pct(candles[last_pivot_idx].close, c.close) >= min_swing_pct:
                peak = candles[last_pivot_idx]
                pivots.append(
                    PivotPoint(
                        timestamp=datetime.fromtimestamp(peak.time, tz=UTC),
                        price=peak.close,
                        kind="H",
                        volume=peak.volume,
                    )
                )
                direction = "down"
                last_pivot_idx = i
                last_pivot_price = c.close
        else:
            if c.close <= candles[last_pivot_idx].close:
                last_pivot_idx = i
            elif pct(c.close, candles[last_pivot_idx].close) >= min_swing_pct:
                trough = candles[last_pivot_idx]
                pivots.append(
                    PivotPoint(
                        timestamp=datetime.fromtimestamp(trough.time, tz=UTC),
                        price=trough.close,
                        kind="L",
                        volume=trough.volume,
                    )
                )
                direction = "up"
                last_pivot_idx = i
                last_pivot_price = c.close

        if len(pivots) >= max_pivots:
            break

    notes = f"zigzag pivots={len(pivots)}, min_swing_pct={min_swing_pct}"
    return CompressedSeries(pivots=pivots, notes=notes)
