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
        params = {"start": start_date.isoformat(), "end": end_date.isoformat()}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get("https://news.futunn.com/api/financial-calendar/list", params=params)
        if response.is_error:
            raise SourceError(f"Futunn calendar request failed: {response.status_code}")
        payload = response.json()
        records = payload.get("data", payload.get("list", [])) if isinstance(payload, dict) else []
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
    date_value = item.get("date") or item.get("time") or item.get("timestamp")
    parsed = datetime.fromisoformat(str(date_value).replace("Z", "+00:00")).date()
    return {
        "date": parsed,
        "country": item.get("country") or item.get("region") or "",
        "category": item.get("category") or "",
        "event": item.get("event") or item.get("title") or item.get("name") or "",
        "importance": int(item.get("importance") or item.get("star") or 0),
        "source": "futunn",
        "actual": item.get("actual"),
        "consensus": item.get("forecast") or item.get("consensus"),
        "previous": item.get("previous"),
    }


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
