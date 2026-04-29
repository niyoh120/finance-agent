"""Futunn public web API data source."""

from __future__ import annotations

import re
from datetime import date, datetime
from html import unescape
from typing import Any

import httpx

from openbb_finance.config import SourceConfig
from openbb_finance.sources.base import DataType, Market, SourceError
from openbb_finance.sources.symbols import cn_plain_symbol, to_openbb_symbol

_CALENDAR_GROUP_DATE_KEY = "_calendar_group_date"
_DEFAULT_NEWS_LIMIT = 50
_HTML_TAG_RE = re.compile(r"<[^>]+>")


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

    async def fetch_news(self, query: str | None, limit: int | None) -> list[dict[str, Any]]:
        requested_limit = limit or _DEFAULT_NEWS_LIMIT
        keyword = _to_futunn_news_keyword(query)
        params = {"keyword": keyword, "size": requested_limit, "sort_type": 2}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get("https://ai-news-search.futunn.com/news_search", params=params)
        if response.is_error:
            raise SourceError(f"Futunn news request failed: {response.status_code}")
        payload = response.json()
        records = payload.get("data", payload.get("list", [])) if isinstance(payload, dict) else []
        return [_normalize_news(item, query=query) for item in records[:requested_limit]]

    async def fetch_world_news(
        self,
        limit: int | None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        requested_limit = limit or _DEFAULT_NEWS_LIMIT
        params = {"pageSize": requested_limit}
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://news.futunn.com/"}
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            response = await client.get("https://news.futunn.com/news-site-api/main/get-flash-list", params=params)
        if response.is_error:
            raise SourceError(f"Futunn world news request failed: {response.status_code}")
        records = _extract_flash_news_records(response.json())
        news = [_normalize_news(item) for item in records[:requested_limit]]
        if start_date or end_date:
            news = [
                item
                for item in news
                if (start_date is None or item["date"].date() >= start_date)
                and (end_date is None or item["date"].date() <= end_date)
            ]
        return news


def _normalize_calendar(item: dict[str, Any]) -> dict[str, Any]:
    data = item.get("itemData", item)
    date_value = item.get(_CALENDAR_GROUP_DATE_KEY) or data.get("date") or data.get("time") or data.get("timestamp")
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
            {**item, _CALENDAR_GROUP_DATE_KEY: group_date}
            for group_date, items in records.items()
            if isinstance(items, list)
            for item in items
            if isinstance(item, dict)
        ]
    return records if isinstance(records, list) else []


def _extract_flash_news_records(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    if isinstance(data, dict):
        nested = data.get("data")
        if isinstance(nested, dict):
            records = nested.get("news", [])
            return records if isinstance(records, list) else []
        records = data.get("news", data.get("list", []))
        return records if isinstance(records, list) else []
    return data if isinstance(data, list) else []


def _parse_calendar_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    text = str(value)
    if text.isdigit():
        timestamp = int(text)
        if timestamp > 10_000_000_000:
            timestamp //= 1000
        return datetime.fromtimestamp(timestamp).date()
    return datetime.fromisoformat(text.replace("/", "-").replace("Z", "+00:00")).date()


def _normalize_news(item: dict[str, Any], query: str | None = None) -> dict[str, Any]:
    date_value = item.get("date") or item.get("time") or item.get("publish_time") or datetime.now().isoformat()
    parsed = _parse_news_datetime(date_value)
    symbols = item.get("symbols") or item.get("relatedStocks") or item.get("quote") or []
    return {
        "date": parsed,
        "title": _clean_text(item.get("title") or item.get("news_title") or item.get("content") or ""),
        "author": item.get("author"),
        "excerpt": item.get("summary") or item.get("excerpt"),
        "body": item.get("content"),
        "url": item.get("url") or item.get("link") or item.get("detailUrl") or "",
        "symbols": _normalize_symbols(symbols, fallback=query),
        "source": "futunn",
    }


def _parse_news_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value)
    if text.isdigit():
        timestamp = int(text)
        if timestamp > 10_000_000_000:
            timestamp //= 1000
        return datetime.fromtimestamp(timestamp)
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _clean_text(value: str) -> str:
    return unescape(_HTML_TAG_RE.sub("", value)).strip()


def _normalize_symbols(value: Any, fallback: str | None = None) -> str | None:
    symbols: list[str] = []
    if isinstance(value, str):
        symbols = [_normalize_news_symbol(value)]
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                symbols.append(_normalize_news_symbol(item))
            elif isinstance(item, dict):
                symbol = item.get("symbol") or item.get("stockCode") or item.get("code") or item.get("name")
                if symbol:
                    symbols.append(_normalize_news_symbol(str(symbol)))
    if not symbols and fallback:
        symbols.append(_normalize_news_symbol(fallback))
    return ",".join(dict.fromkeys(symbols)) or None


def _to_futunn_news_keyword(query: str | None) -> str:
    if not query:
        return ""
    return cn_plain_symbol(query) or query.strip().upper()


def _normalize_news_symbol(symbol: str) -> str:
    return to_openbb_symbol(symbol)
