"""Eastmoney search data source."""

from __future__ import annotations

import json
from typing import Any

import httpx

from openbb_finance.config import SourceConfig
from openbb_finance.sources.base import DataType, Market, SourceError
from openbb_finance.sources.symbols import cn_plain_symbol, to_openbb_symbol


class EastmoneySource:
    """Eastmoney search API for US/HK/CN stocks."""

    name = "eastmoney"

    def __init__(self, config: SourceConfig) -> None:
        self.enabled = config.enabled
        self.priority = config.priority

    def supports(self, market: Market, data_type: DataType, **kwargs: Any) -> bool:
        del market, kwargs
        return data_type == "search"

    async def fetch_equity_search(self, query: str, is_symbol: bool | None = None) -> list[dict[str, Any]]:
        """Search stocks via Eastmoney API.

        Supports Chinese and English search for US/HK/CN stocks.
        """
        url = "https://searchapi.eastmoney.com/api/suggest/get"
        params = {"input": query, "type": "14", "count": 20, "cb": ""}
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.eastmoney.com/"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params, headers=headers)

        if response.is_error:
            raise SourceError(f"Eastmoney search request failed: {response.status_code}")

        text = response.text.strip()
        if text.startswith("(") and text.endswith(")"):
            text = text[1:-1]

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SourceError(f"Eastmoney returned invalid JSON: {exc}") from exc

        items = data.get("QuotationCodeTable", {}).get("Data", [])
        if not isinstance(items, list):
            return []

        query_text = query.strip().upper()
        results: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            classify = item.get("Classify")
            if classify not in {"AStock", "HK", "UsStock"}:
                continue
            code = str(item.get("Code", "")).strip()
            name = str(item.get("Name", "")).strip()
            if not code:
                continue
            symbol = self._normalize_symbol(code, classify)
            if is_symbol:
                # Only match against symbol/code, not name
                if not self._symbol_matches(query_text, code, symbol, classify):
                    continue
            results.append({"symbol": symbol, "name": name, "source": "eastmoney"})

        return results

    def _symbol_matches(self, query: str, code: str, symbol: str, classify: str) -> bool:
        """Check if query matches the symbol/code."""
        # Match against original code
        if query in code.upper():
            return True
        # Match against normalized symbol
        if query in symbol.upper():
            return True
        # For A-shares, also match against plain digit code
        if classify == "AStock":
            plain = cn_plain_symbol(query)
            if plain and plain in code:
                return True
        # For HK stocks, also match against 4-digit code without .HK suffix
        if classify == "HK":
            hk_code = symbol.replace(".HK", "")
            if query in hk_code:
                return True
        return False

    def _normalize_symbol(self, code: str, classify: str) -> str:
        """Normalize symbol to standard format."""
        if classify == "AStock":
            return to_openbb_symbol(code)
        if classify == "HK":
            return normalize_hk_symbol(code)
        return code


def normalize_hk_symbol(code: str) -> str:
    """Normalize HK symbol to XXXX.HK format.

    Eastmoney returns codes like "00700", convert to "0700.HK".
    """
    if not code.isdigit():
        return code
    stripped = code.lstrip("0") or "0"
    padded = stripped.zfill(4)
    return f"{padded}.HK"
