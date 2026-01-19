from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

from .schemas import Candle, MovingAverageCross, MovingAverages, Timeframe


@dataclass(frozen=True)
class DerivedFeatures:
    timeframe: Timeframe
    slope_ma50: float | None
    slope_ma200: float | None
    last_close: float
    last_timestamp: datetime


def _series_sma(values: list[float], window: int) -> list[float | None]:
    s = pd.Series(values, dtype="float64")
    sma = s.rolling(window=window, min_periods=window).mean()
    return [None if pd.isna(v) else float(v) for v in sma.to_list()]


def compute_moving_averages(
    *, timeframe: Timeframe, candles: list[Candle]
) -> MovingAverages:
    closes = [c.close for c in candles]
    ma50 = _series_sma(closes, 50)
    ma200 = _series_sma(closes, 200)

    crosses: list[MovingAverageCross] = []
    for i in range(1, len(candles)):
        a0, b0 = ma50[i - 1], ma200[i - 1]
        a1, b1 = ma50[i], ma200[i]
        if a0 is None or b0 is None or a1 is None or b1 is None:
            continue
        # Detect sign change of (ma50 - ma200)
        d0 = a0 - b0
        d1 = a1 - b1
        if d0 == 0:
            continue
        if (d0 < 0 and d1 > 0) or (d0 > 0 and d1 < 0):
            kind = "golden" if d0 < 0 and d1 > 0 else "death"
            crosses.append(
                MovingAverageCross(
                    timestamp=datetime.fromtimestamp(candles[i].time, tz=UTC),
                    kind=kind,
                    price=candles[i].close,
                )
            )

    return MovingAverages(timeframe=timeframe, ma50=ma50, ma200=ma200, crosses=crosses)


def compute_derived_features(
    *, timeframe: Timeframe, candles: list[Candle], ma: MovingAverages
) -> DerivedFeatures:
    if not candles:
        raise ValueError("candles is empty")

    def slope(series: list[float | None], lookback: int = 20) -> float | None:
        idx = len(series) - 1
        if idx < lookback:
            return None
        a = series[idx]
        b = series[idx - lookback]
        if a is None or b is None:
            return None
        return (a - b) / lookback

    last = candles[-1]
    return DerivedFeatures(
        timeframe=timeframe,
        slope_ma50=slope(ma.ma50),
        slope_ma200=slope(ma.ma200),
        last_close=last.close,
        last_timestamp=datetime.fromtimestamp(last.time, tz=UTC),
    )
