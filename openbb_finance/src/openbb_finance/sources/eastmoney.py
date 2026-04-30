"""Eastmoney search data source."""

from __future__ import annotations

import json
from typing import Any, Literal

import httpx

from openbb_finance.config import SourceConfig
from openbb_finance.sources.base import DataType, Market, SourceError
from openbb_finance.sources.symbols import cn_plain_symbol, to_openbb_symbol


class EastmoneySource:
    """Eastmoney search API for US/HK/CN stocks and indices."""

    name = "eastmoney"

    def __init__(self, config: SourceConfig) -> None:
        self.enabled = config.enabled
        self.priority = config.priority

    def supports(self, market: Market, data_type: DataType, **kwargs: Any) -> bool:
        del market, kwargs
        return data_type in {"search", "index_search", "index_snapshots"}

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
                if not self._symbol_matches(query_text, code, symbol, classify):
                    continue
            results.append({"symbol": symbol, "name": name, "source": "eastmoney"})

        return results

    async def fetch_index_search(self, query: str, is_symbol: bool | None = None) -> list[dict[str, Any]]:
        """Search indices via Eastmoney API.

        Supports Chinese and English search for CN/US/HK indices.
        """
        url = "https://searchapi.eastmoney.com/api/suggest/get"
        params = {"input": query, "type": "14", "count": 50, "cb": ""}
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
            if not self._is_index(item):
                continue
            code = str(item.get("Code", "")).strip()
            name = str(item.get("Name", "")).strip()
            if not code:
                continue
            symbol = self._normalize_index_symbol(code, item.get("Classify", ""))
            if is_symbol:
                if query_text not in code.upper() and query_text not in symbol.upper():
                    continue
            results.append({"symbol": symbol, "name": name, "source": "eastmoney"})

        return results

    async def fetch_index_snapshots(
        self,
        region: Literal["cn", "us", "hk"],
        symbols: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch index snapshots via Eastmoney API.

        Args:
            region: Market region - cn, us, or hk
            symbols: Optional list of specific symbols to fetch

        Returns:
            List of index snapshot data
        """
        if symbols:
            secids = self._build_secids(symbols, region)
        else:
            secids = self._default_secids(region)

        if not secids:
            return []

        url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
        params = {
            "fltt": "2",
            "secids": secids,
            "fields": "f12,f14,f2,f3,f4,f15,f16,f17,f18,f5,f6",
        }
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.eastmoney.com/"}

        async with httpx.AsyncClient(timeout=10.0, http2=False) as client:
            response = await client.get(url, params=params, headers=headers)

        if response.is_error:
            raise SourceError(f"Eastmoney snapshots request failed: {response.status_code}")

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise SourceError(f"Eastmoney returned invalid JSON: {exc}") from exc

        items = data.get("data", {}).get("diff", [])
        if not isinstance(items, list):
            return []

        results: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            results.append({
                "symbol": str(item.get("f12", "")),
                "name": str(item.get("f14", "")),
                "price": item.get("f2"),
                "change_percent": item.get("f3"),
                "change": item.get("f4"),
                "high": item.get("f15"),
                "low": item.get("f16"),
                "open": item.get("f17"),
                "prev_close": item.get("f18"),
                "volume": item.get("f5"),
                "amount": item.get("f6"),
                "source": "eastmoney",
            })

        return results

    def _is_index(self, item: dict[str, Any]) -> bool:
        """Check if the item is an index."""
        classify = item.get("Classify", "")
        security_type = item.get("SecurityType")
        
        # A股指数
        if classify == "Index":
            return True
        # 全球指数 (SPX, DJI, NDX 等)
        if classify == "UniversalIndex":
            return True
        # 港股指数 (HSI 等)
        if classify == "HK" and security_type == "11":
            return True
        return False

    def _normalize_index_symbol(self, code: str, classify: str) -> str:
        """Normalize index symbol to standard format."""
        # A股指数保持原样
        if classify == "Index":
            return code
        # 全球指数和港股指数保持原样
        return code

    def _build_secids(self, symbols: list[str], region: str) -> str:
        """Build secids parameter for Eastmoney API."""
        market_code = self._market_code(region)
        return ",".join(f"{market_code}.{s}" for s in symbols)

    def _market_code(self, region: str) -> str:
        """Get Eastmoney market code for region."""
        codes = {
            "cn": "1",  # 上证指数用 1，深证用 2
            "us": "100",
            "hk": "100",
        }
        return codes.get(region, "1")

    def _default_secids(self, region: str) -> str:
        """Get default secids for region."""
        defaults = {
            "cn": "1.000001,1.000016,1.000300,1.000905,1.000852,2.399001,2.399006",
            "us": "100.SPX,100.DJI,100.NDX",
            "hk": "100.HSI,100.HSCEI,100.HSTECH",
        }
        return defaults.get(region, "")

    def _symbol_matches(self, query: str, code: str, symbol: str, classify: str) -> bool:
        """Check if query matches the symbol/code."""
        if query in code.upper():
            return True
        if query in symbol.upper():
            return True
        if classify == "AStock":
            plain = cn_plain_symbol(query)
            if plain and plain in code:
                return True
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
