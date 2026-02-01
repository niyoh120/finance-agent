from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def fetch_stock_history(
    *,
    base_url: str,
    symbol: str,
    timeframe: str = "D",
    range: int = 200,
    to: int | None = None,
) -> list[Candle]:
    url = base_url.rstrip("/") + "/history"
    params: dict[str, Any] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "range": range,
    }
    if to is not None:
        params["to"] = to

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()

    candles = payload.get("candles", []) if isinstance(payload, dict) else []

    result: list[Candle] = []
    for item in candles:
        result.append(
            Candle(
                timestamp=int(item.get("timestamp")),
                open=float(item.get("open")),
                high=float(item.get("high")),
                low=float(item.get("low")),
                close=float(item.get("close")),
                volume=float(item.get("volume")),
            )
        )
    return result
