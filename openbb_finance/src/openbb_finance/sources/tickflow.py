"""TickFlow data source."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

import httpx

from openbb_finance.config import SourceConfig
from openbb_finance.sources.base import DataType, Market, PriceQuery, SourceError, normalize_interval
from openbb_finance.sources.symbols import is_cn_symbol, split_symbol, to_openbb_symbol


class TickflowSource:
    name = "tickflow"

    def __init__(self, config: SourceConfig) -> None:
        self.enabled = config.enabled
        self.priority = config.priority
        self.api_key = config.api_key
        self.base_url = "https://api.tickflow.org"

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
        requested = symbols or _default_index_symbols(region)
        tickflow_symbols = [_to_tickflow_symbol(symbol) for symbol in requested]
        output_symbols = dict(zip(tickflow_symbols, [_normalize_output_symbol(symbol, region) for symbol in requested], strict=False))
        items = await self._fetch_quotes(tickflow_symbols)
        return [_normalize_index_snapshot(item, output_symbols.get(str(item.get("symbol")), str(item.get("symbol")))) for item in items]

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


def _normalize_output_symbol(symbol: str, region: str) -> str:
    if region == "cn":
        return to_openbb_symbol(symbol)
    return symbol.strip().upper()


def _default_index_symbols(region: str) -> list[str]:
    defaults = {
        "cn": ["000001.XSHG", "000016.XSHG", "000300.XSHG", "000905.XSHG", "399001.XSHE", "399006.XSHE"],
        "us": ["SPX"],
        "hk": ["HSI"],
    }
    return defaults.get(region, [])


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
        "date": parsed.date(),
        "open": float(item["open"]),
        "high": float(item["high"]),
        "low": float(item["low"]),
        "close": float(item["close"]),
        "volume": float(item["volume"]) if item.get("volume") is not None else None,
        "amount": float(item["amount"]) if item.get("amount") is not None else None,
        "source": "tickflow",
    }
