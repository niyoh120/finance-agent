"""TickFlow data source."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from openbb_finance.config import SourceConfig
from openbb_finance.sources.base import DataType, Market, PriceQuery, SourceError, normalize_interval


class TickflowSource:
    name = "tickflow"

    def __init__(self, config: SourceConfig) -> None:
        self.enabled = config.enabled
        self.priority = config.priority
        self.api_key = config.api_key
        self.base_url = "https://api.tickflow.org"

    def supports(self, market: Market, data_type: DataType, **kwargs: Any) -> bool:
        del kwargs
        return market in {"cn", "us", "hk"} and data_type == "price"

    async def fetch_quote(self, symbol: str) -> dict[str, Any]:
        if not self.api_key:
            raise SourceError("TickFlow API key is required")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{self.base_url}/api/v1/quote", params={"symbol": symbol}, headers=headers)
        if response.is_error:
            raise SourceError(f"TickFlow quote request failed: {response.status_code}")
        payload = response.json()
        item = payload.get("data", payload)
        return {
            "symbol": symbol,
            "name": item.get("name"),
            "last_price": float(item["price"]) if item.get("price") is not None else None,
            "open": float(item["open"]) if item.get("open") is not None else None,
            "high": float(item["high"]) if item.get("high") is not None else None,
            "low": float(item["low"]) if item.get("low") is not None else None,
            "prev_close": float(item["prev_close"]) if item.get("prev_close") is not None else None,
            "volume": float(item["volume"]) if item.get("volume") is not None else None,
            "change": float(item["change"]) if item.get("change") is not None else None,
            "change_percent": float(item["change_percent"]) if item.get("change_percent") is not None else None,
            "source": "tickflow",
        }

    async def fetch_price(self, query: PriceQuery) -> list[dict[str, Any]]:
        if not self.api_key:
            raise SourceError("TickFlow API key is required")
        params = {
            "symbol": query.symbol,
            "interval": normalize_interval(query.interval),
        }
        if query.start_date:
            params["start_date"] = query.start_date.isoformat()
        if query.end_date:
            params["end_date"] = query.end_date.isoformat()
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{self.base_url}/api/v1/kline", params=params, headers=headers)
        if response.is_error:
            raise SourceError(f"TickFlow request failed: {response.status_code}")
        payload = response.json()
        records = payload.get("data", payload if isinstance(payload, list) else [])
        return [_normalize_record(item, query.symbol) for item in records]


def _normalize_record(item: dict[str, Any], symbol: str) -> dict[str, Any]:
    date_value = item.get("date") or item.get("time") or item.get("timestamp")
    parsed = datetime.fromisoformat(str(date_value).replace("Z", "+00:00"))
    return {
        "symbol": symbol,
        "date": parsed.date(),
        "open": float(item["open"]),
        "high": float(item["high"]),
        "low": float(item["low"]),
        "close": float(item["close"]),
        "volume": float(item["volume"]) if item.get("volume") is not None else None,
        "source": "tickflow",
    }
