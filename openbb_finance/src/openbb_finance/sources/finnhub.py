"""Finnhub news data source."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import httpx

from openbb_finance.config import SourceConfig
from openbb_finance.sources.base import DataType, Market, SourceError

_DEFAULT_NEWS_LIMIT = 50
_DEFAULT_COMPANY_NEWS_DAYS = 7


class FinnhubSource:
    name = "finnhub"

    def __init__(self, config: SourceConfig) -> None:
        self.api_key = config.api_key
        # Finnhub requires an API key; skip the source when none is configured.
        self.enabled = config.enabled and bool(self.api_key)
        self.base_url = (config.base_url or "https://finnhub.io/api/v1").rstrip("/")

    def supports(self, market: Market, data_type: DataType, **kwargs: Any) -> bool:
        del kwargs
        return data_type == "news" and market in {"us", "global"}

    async def fetch_news(self, query: str | None, limit: int | None) -> list[dict[str, Any]]:
        if not query:
            return []
        requested_limit = limit or _DEFAULT_NEWS_LIMIT
        end_date = date.today()
        start_date = end_date - timedelta(days=_DEFAULT_COMPANY_NEWS_DAYS)
        records = await self._get(
            "/company-news",
            {
                "symbol": query.strip().upper(),
                "from": start_date.isoformat(),
                "to": end_date.isoformat(),
            },
        )
        if not isinstance(records, list):
            return []
        return [_normalize_news(item) for item in records[:requested_limit] if isinstance(item, dict)]

    async def fetch_world_news(
        self,
        limit: int | None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        requested_limit = limit or _DEFAULT_NEWS_LIMIT
        records = await self._get("/news", {"category": "general"})
        if not isinstance(records, list):
            return []
        news = [_normalize_news(item) for item in records if isinstance(item, dict)]
        if start_date or end_date:
            news = [
                item
                for item in news
                if (start_date is None or item["date"].date() >= start_date)
                and (end_date is None or item["date"].date() <= end_date)
            ]
        return news[:requested_limit]

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        if not self.api_key:
            raise SourceError("Finnhub API key is required")
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}{path}",
                params={**params, "token": self.api_key},
            )
        if response.is_error:
            raise SourceError(f"Finnhub request failed: {response.status_code}")
        return response.json()


def _normalize_news(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": _parse_datetime(item.get("datetime")),
        "title": item.get("headline") or "",
        "author": item.get("source"),
        "excerpt": item.get("summary"),
        "body": None,
        "images": item.get("image"),
        "url": item.get("url") or "",
        "symbols": item.get("related") or None,
        "source": "finnhub",
    }


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return _from_timestamp(value)
    text = str(value or "")
    if text.isdigit():
        return _from_timestamp(int(text))
    if not text:
        return datetime.now()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now()


def _from_timestamp(value: int | float) -> datetime:
    try:
        return datetime.fromtimestamp(value)
    except (OSError, OverflowError, ValueError):
        return datetime.now()
