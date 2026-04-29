"""Futunn public web API data source."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import httpx

from openbb_finance.config import SourceConfig
from openbb_finance.sources.base import DataType, Market, SourceError


class FutunnSource:
    name = "futunn"

    def __init__(self, config: SourceConfig) -> None:
        self.enabled = config.enabled
        self.priority = config.priority

    def supports(self, market: Market, data_type: DataType, **kwargs: Any) -> bool:
        del market, kwargs
        return data_type in {"calendar", "news"}

    async def fetch_economic_calendar(self, start_date: date, end_date: date) -> list[dict[str, Any]]:
        params = {
            "tabs": "1",
            "startTime": start_date.strftime("%Y/%m/%d"),
            "endTime": end_date.strftime("%Y/%m/%d") if end_date != start_date else "",
            "rangeType": "1",
            "nation": "",
            "star": "",
            "clientLang": "2",
            "marketList": "",
            "ipoMarketList": "",
            "seqMark": "",
            "timeZone": "UTC",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get("https://news.futunn.com/api/financial-calendar/list", params=params)
        if response.is_error:
            raise SourceError(f"Futunn calendar request failed: {response.status_code}")
        payload = response.json()
        records = _extract_calendar_records(payload)
        return [_normalize_calendar(item) for item in records]

    async def fetch_news(self, query: str | None, limit: int) -> list[dict[str, Any]]:
        params = {"keyword": query or "", "limit": limit}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get("https://ai-news-search.futunn.com/news_search", params=params)
        if response.is_error:
            raise SourceError(f"Futunn news request failed: {response.status_code}")
        payload = response.json()
        records = payload.get("data", payload.get("list", [])) if isinstance(payload, dict) else []
        return [_normalize_news(item) for item in records[:limit]]


def _normalize_calendar(item: dict[str, Any]) -> dict[str, Any]:
    data = item.get("itemData", item)
    date_value = data.get("date") or data.get("time") or data.get("timestamp")
    parsed = _parse_calendar_date(date_value)
    return {
        "date": parsed,
        "country": data.get("country") or data.get("region") or data.get("stockMarket") or "",
        "category": data.get("category") or "",
        "event": data.get("event") or data.get("title") or data.get("name") or "",
        "importance": str(data.get("importance") or data.get("star") or ""),
        "source": "futunn",
        "actual": data.get("actual"),
        "consensus": data.get("forecast") or data.get("consensus"),
        "previous": data.get("previous"),
    }


def _extract_calendar_records(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return data if isinstance(data, list) else []
    records = data.get("list", [])
    if isinstance(records, dict):
        return [
            item for items in records.values() if isinstance(items, list) for item in items if isinstance(item, dict)
        ]
    return records if isinstance(records, list) else []


def _parse_calendar_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    text = str(value)
    if text.isdigit():
        timestamp = int(text)
        if timestamp > 10_000_000_000:
            timestamp //= 1000
        return datetime.fromtimestamp(timestamp).date()
    return datetime.fromisoformat(text.replace("Z", "+00:00")).date()


def _normalize_news(item: dict[str, Any]) -> dict[str, Any]:
    date_value = item.get("date") or item.get("time") or item.get("publish_time") or datetime.now().isoformat()
    parsed = datetime.fromisoformat(str(date_value).replace("Z", "+00:00"))
    return {
        "date": parsed,
        "title": item.get("title") or item.get("news_title") or "",
        "author": item.get("author"),
        "excerpt": item.get("summary") or item.get("excerpt"),
        "body": item.get("content"),
        "url": item.get("url") or item.get("link"),
        "symbols": item.get("symbols") or [],
        "source": "futunn",
    }
