"""TickFlow data source."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

import httpx

from openbb_finance.config import SourceConfig
from openbb_finance.sources.base import DataType, Market, PriceQuery, SourceError, normalize_interval
from openbb_finance.sources.symbols import is_cn_symbol, split_symbol, to_openbb_symbol

TICKFLOW_INDEX_METADATA: list[dict[str, str]] = [
    {"symbol": "000001.XSHG", "name": "上证指数", "exchange": "XSHG", "currency": "CNY", "region": "cn"},
    {"symbol": "000016.XSHG", "name": "上证50", "exchange": "XSHG", "currency": "CNY", "region": "cn"},
    {"symbol": "000300.XSHG", "name": "沪深300", "exchange": "XSHG", "currency": "CNY", "region": "cn"},
    {"symbol": "000905.XSHG", "name": "中证500", "exchange": "XSHG", "currency": "CNY", "region": "cn"},
    {"symbol": "000852.XSHG", "name": "中证1000", "exchange": "XSHG", "currency": "CNY", "region": "cn"},
    {"symbol": "399001.XSHE", "name": "深证成指", "exchange": "XSHE", "currency": "CNY", "region": "cn"},
    {"symbol": "399005.XSHE", "name": "中小100", "exchange": "XSHE", "currency": "CNY", "region": "cn"},
    {"symbol": "399006.XSHE", "name": "创业板指", "exchange": "XSHE", "currency": "CNY", "region": "cn"},
    {"symbol": "399106.XSHE", "name": "深证综指", "exchange": "XSHE", "currency": "CNY", "region": "cn"},
    {"symbol": "SPX", "name": "S&P 500", "exchange": "US", "currency": "USD", "region": "us"},
    {"symbol": "DJI", "name": "Dow Jones Industrial Average", "exchange": "US", "currency": "USD", "region": "us"},
    {"symbol": "IXIC", "name": "NASDAQ Composite", "exchange": "US", "currency": "USD", "region": "us"},
    {"symbol": "NDX", "name": "NASDAQ 100", "exchange": "US", "currency": "USD", "region": "us"},
    {"symbol": "RUT", "name": "Russell 2000", "exchange": "US", "currency": "USD", "region": "us"},
    {"symbol": "VIX", "name": "CBOE Volatility Index", "exchange": "US", "currency": "USD", "region": "us"},
    {"symbol": "HSI", "name": "恒生指数", "exchange": "HKEX", "currency": "HKD", "region": "hk"},
    {"symbol": "HSCEI", "name": "恒生中国企业指数", "exchange": "HKEX", "currency": "HKD", "region": "hk"},
    {"symbol": "HSTECH", "name": "恒生科技指数", "exchange": "HKEX", "currency": "HKD", "region": "hk"},
]


def static_available_indices() -> list[dict[str, str]]:
    return [
        {key: value for key, value in item.items() if key != "region"} | {"source": "tickflow"}
        for item in TICKFLOW_INDEX_METADATA
    ]


class TickflowSource:
    name = "tickflow"

    def __init__(self, config: SourceConfig) -> None:
        self.enabled = config.enabled
        self.priority = config.priority
        self.api_key = config.api_key
        self.base_url = config.base_url or "https://api.tickflow.org"

    def supports(self, market: Market, data_type: DataType, **kwargs: Any) -> bool:
        del kwargs
        if data_type == "index_snapshots":
            return market in {"cn", "us", "hk", "global"}
        return market in {"cn", "us", "hk"} and data_type == "price"

    async def fetch_quote(self, symbol: str) -> dict[str, Any]:
        if not self.api_key:
            raise SourceError("TickFlow API key is required")
        items = await self._fetch_quotes([_to_tickflow_symbol(symbol)])
        if not items:
            raise SourceError(f"TickFlow quote returned no data for {symbol}")
        return _normalize_quote(items[0], symbol)

    async def fetch_index_snapshots(
        self,
        region: str,
        symbols: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not self.api_key:
            raise SourceError("TickFlow API key is required")
        metadata = _default_index_metadata(region)
        requested = symbols or [item["symbol"] for item in metadata]
        tickflow_symbols = [
            _to_tickflow_index_symbol(symbol, _index_symbol_region(symbol, metadata, region))
            for symbol in requested
        ]
        output_symbols = dict(
            zip(tickflow_symbols, [_normalize_output_symbol(symbol, region) for symbol in requested], strict=False)
        )
        items = await self._fetch_quotes(tickflow_symbols)
        return [
            _normalize_index_snapshot(item, output_symbols.get(str(item.get("symbol")), str(item.get("symbol"))))
            for item in items
        ]

    async def fetch_available_indices(self) -> list[dict[str, Any]]:
        if not self.api_key:
            raise SourceError("TickFlow API key is required")
        universes = await self._fetch_universes()
        index_universe_ids = [
            str(item["id"])
            for item in universes
            if isinstance(item, dict) and str(item.get("category", "")).lower() == "index" and item.get("id")
        ]
        if not index_universe_ids:
            return []
        universe_details = await self._fetch_universe_details(index_universe_ids)
        symbols = _unique_symbols(
            symbol
            for detail in universe_details
            for symbol in detail.get("symbols", [])
            if isinstance(symbol, str)
        )
        if not symbols:
            return []
        instruments = await self._fetch_instruments(symbols)
        return [_normalize_available_index(item) for item in instruments if item.get("type") == "index"]

    async def _fetch_universes(self) -> list[dict[str, Any]]:
        response = await self._get("/v1/universes")
        data = response.get("data", [])
        return data if isinstance(data, list) else []

    async def _fetch_universe_details(self, ids: list[str]) -> list[dict[str, Any]]:
        details: list[dict[str, Any]] = []
        for chunk in _chunks(ids, 50):
            response = await self._post("/v1/universes/batch", {"ids": chunk})
            data = response.get("data", {})
            if isinstance(data, dict):
                details.extend(item for item in data.values() if isinstance(item, dict))
        return details

    async def _fetch_instruments(self, symbols: list[str]) -> list[dict[str, Any]]:
        instruments: list[dict[str, Any]] = []
        for chunk in _chunks(symbols, 1000):
            response = await self._post("/v1/instruments", {"symbols": chunk})
            data = response.get("data", [])
            if isinstance(data, list):
                instruments.extend(item for item in data if isinstance(item, dict))
        return instruments

    async def _fetch_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        headers = {"x-api-key": self.api_key or ""}
        items: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for chunk in _chunks(symbols, 5):
                response = await client.get(
                    f"{self.base_url}/v1/quotes",
                    params={"symbols": ",".join(chunk)},
                    headers=headers,
                )
                if response.is_error:
                    raise SourceError(f"TickFlow quotes request failed: {response.status_code}")
                data = response.json().get("data", [])
                if isinstance(data, list):
                    items.extend(item for item in data if isinstance(item, dict))
        return items

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"x-api-key": self.api_key or ""}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{self.base_url}{path}", params=params, headers=headers)
        if response.is_error:
            raise SourceError(f"TickFlow request failed: {response.status_code}")
        data = response.json()
        return data if isinstance(data, dict) else {}

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"x-api-key": self.api_key or ""}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{self.base_url}{path}", json=payload, headers=headers)
        if response.is_error:
            raise SourceError(f"TickFlow request failed: {response.status_code}")
        data = response.json()
        return data if isinstance(data, dict) else {}

    async def fetch_price(self, query: PriceQuery) -> list[dict[str, Any]]:
        if not self.api_key:
            raise SourceError("TickFlow API key is required")
        params = {
            "symbol": _to_tickflow_symbol(query.symbol),
            "period": normalize_interval(query.interval),
            "adjust": "forward" if query.adjusted else "none",
        }
        if query.start_date:
            params["start_time"] = _to_timestamp_ms(query.start_date, is_end=False)
        if query.end_date:
            params["end_time"] = _to_timestamp_ms(query.end_date, is_end=True)
        headers = {"X-API-Key": self.api_key}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{self.base_url}/v1/klines", params=params, headers=headers)
        if response.is_error:
            raise SourceError(f"TickFlow request failed: {response.status_code}")
        payload = response.json()
        records = _extract_records(payload, query.symbol)
        return [_normalize_record(item, query.symbol) for item in records]


def _normalize_quote(item: dict[str, Any], symbol: str) -> dict[str, Any]:
    ext = item.get("ext") if isinstance(item.get("ext"), dict) else {}
    return {
        "symbol": symbol,
        "name": ext.get("name"),
        "last_price": float(item["last_price"]) if item.get("last_price") is not None else None,
        "open": float(item["open"]) if item.get("open") is not None else None,
        "high": float(item["high"]) if item.get("high") is not None else None,
        "low": float(item["low"]) if item.get("low") is not None else None,
        "prev_close": float(item["prev_close"]) if item.get("prev_close") is not None else None,
        "volume": float(item["volume"]) if item.get("volume") is not None else None,
        "change": float(ext["change_amount"]) if ext.get("change_amount") is not None else None,
        "change_percent": float(ext["change_pct"]) * 100 if ext.get("change_pct") is not None else None,
        "source": "tickflow",
    }


def _normalize_index_snapshot(item: dict[str, Any], symbol: str) -> dict[str, Any]:
    quote = _normalize_quote(item, symbol)
    return {
        "symbol": symbol,
        "name": quote["name"],
        "currency": _currency(item.get("region")),
        "price": quote["last_price"],
        "open": quote["open"],
        "high": quote["high"],
        "low": quote["low"],
        "close": quote["last_price"],
        "volume": int(quote["volume"]) if quote["volume"] is not None else None,
        "prev_close": quote["prev_close"],
        "change": quote["change"],
        "change_percent": quote["change_percent"],
        "source": "tickflow",
    }


def _to_tickflow_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if not is_cn_symbol(value):
        code, suffix = split_symbol(value)
        if suffix == "HK" and code.isdigit():
            return f"{code.zfill(5)}.HK"
        if suffix:
            return value
        if code.isalpha():
            return f"{code}.US"
        return value
    code, suffix = split_symbol(value)
    if suffix in {"SH", "SS", "XSHG"}:
        return f"{code}.SH"
    if suffix in {"SZ", "XSHE"}:
        return f"{code}.SZ"
    if code.startswith(("5", "6", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"


def _to_tickflow_index_symbol(symbol: str, region: str) -> str:
    value = symbol.strip().upper()
    code, suffix = split_symbol(value)
    if region == "hk" and not suffix and code.isalpha():
        return f"{code}.HK"
    return _to_tickflow_symbol(value)


def _normalize_output_symbol(symbol: str, region: str) -> str:
    if region == "cn":
        return to_openbb_symbol(symbol)
    return symbol.strip().upper()


def _default_index_metadata(region: str) -> list[dict[str, str]]:
    normalized_region = region.lower()
    if normalized_region == "global":
        return TICKFLOW_INDEX_METADATA.copy()
    return [item for item in TICKFLOW_INDEX_METADATA if item["region"] == normalized_region]


def _index_symbol_region(symbol: str, metadata: list[dict[str, str]], fallback_region: str) -> str:
    value = symbol.strip().upper()
    return next((item["region"] for item in metadata if item["symbol"] == value), fallback_region)


def _unique_symbols(symbols: Any) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for symbol in symbols:
        value = str(symbol).strip().upper()
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _normalize_available_index(item: dict[str, Any]) -> dict[str, Any]:
    symbol = str(item.get("symbol", "")).strip().upper()
    region = str(item.get("region", "")).upper()
    exchange = str(item.get("exchange", "")).upper() or None
    return {
        "symbol": _normalize_available_index_symbol(symbol, region),
        "name": item.get("name"),
        "exchange": _openbb_exchange(exchange),
        "currency": _currency(region),
        "source": "tickflow",
    }


def _normalize_available_index_symbol(symbol: str, region: str) -> str:
    code, suffix = split_symbol(symbol)
    if region == "CN":
        return to_openbb_symbol(symbol)
    if region in {"US", "HK"} and suffix == region and code.isalpha():
        return code
    return symbol


def _openbb_exchange(exchange: str | None) -> str | None:
    return {"SH": "XSHG", "SZ": "XSHE", "HK": "HKEX"}.get(exchange or "", exchange)


def _currency(region: Any) -> str | None:
    return {"CN": "CNY", "US": "USD", "HK": "HKD"}.get(str(region))


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _extract_records(payload: Any, symbol: str) -> list[dict[str, Any]]:
    data = payload.get("data", payload if isinstance(payload, list) else [])
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []

    timestamps = data.get("timestamp") or data.get("time") or data.get("date") or []
    rows: list[dict[str, Any]] = []
    for index, timestamp in enumerate(timestamps):
        row = {
            "symbol": symbol,
            "timestamp": timestamp,
            "open": data["open"][index],
            "high": data["high"][index],
            "low": data["low"][index],
            "close": data["close"][index],
            "volume": (data.get("volume") or [None] * len(timestamps))[index],
        }
        amount = (data.get("amount") or [None] * len(timestamps))[index]
        if amount is not None:
            row["amount"] = amount
        rows.append(row)
    return rows


def _to_timestamp_ms(value: date, *, is_end: bool) -> int:
    moment = datetime.combine(value, time.max if is_end else time.min)
    return int(moment.timestamp() * 1000)


def _normalize_record(item: dict[str, Any], symbol: str) -> dict[str, Any]:
    date_value = item.get("date") or item.get("time") or item.get("timestamp")
    if isinstance(date_value, int | float):
        timestamp = float(date_value)
        parsed = datetime.fromtimestamp(timestamp / 1000 if timestamp > 10_000_000_000 else timestamp)
    else:
        parsed = datetime.fromisoformat(str(date_value).replace("Z", "+00:00"))
    return {
        "symbol": symbol,
        "date": parsed,
        "open": float(item["open"]),
        "high": float(item["high"]),
        "low": float(item["low"]),
        "close": float(item["close"]),
        "volume": float(item["volume"]) if item.get("volume") is not None else None,
        "amount": float(item["amount"]) if item.get("amount") is not None else None,
        "source": "tickflow",
    }
