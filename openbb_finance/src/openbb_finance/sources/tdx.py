"""TDX API data source."""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any

import httpx

from openbb_finance.config import SourceConfig
from openbb_finance.sources.base import (
    DataType,
    Market,
    PriceQuery,
    SourceError,
    is_intraday_interval,
    normalize_interval,
)
from openbb_finance.sources.symbols import cn_exchange, cn_plain_symbol, split_symbol, to_openbb_symbol

ADJUST_FACTOR_START_DATE = date(1990, 1, 1)


class TdxSource:
    name = "tdx"

    def __init__(self, config: SourceConfig) -> None:
        self.enabled = config.enabled
        self.priority = config.priority
        self.base_url = (config.base_url or "https://tdx-api.niyoh.top").rstrip("/")

    def supports(self, market: Market, data_type: DataType, **kwargs: Any) -> bool:
        del kwargs
        return market == "cn" and data_type in {"price", "search"}

    async def fetch_quote(self, symbol: str) -> dict[str, Any]:
        code = _to_tdx_code(symbol)
        payload = await self._get("/api/quote", {"code": code})
        items = _response_data(payload)
        if not isinstance(items, list) or not items:
            raise SourceError(f"TDX quote returned no data for {symbol}")
        item = next((value for value in items if isinstance(value, dict) and str(value.get("Code")) == code), items[0])
        if not isinstance(item, dict):
            raise SourceError(f"TDX quote returned invalid data for {symbol}")
        return _normalize_quote(item, symbol)

    async def fetch_price(self, query: PriceQuery) -> list[dict[str, Any]]:
        interval = normalize_interval(query.interval)
        params: dict[str, Any] = {
            "code": _to_tdx_code(query.symbol),
            "type": _to_tdx_interval(interval),
        }

        payload = await self._get(_to_tdx_kline_path(interval, query.adjusted), params)
        data = _response_data(payload)
        if not isinstance(data, dict):
            return []
        rows = data.get("List") or data.get("list") or []
        if not isinstance(rows, list):
            return []
        records = [_normalize_price_row(row, query.symbol) for row in rows if isinstance(row, dict)]
        filtered = [
            record
            for record in records
            if (query.start_date is None or _as_date(record["date"]) >= query.start_date)
            and (query.end_date is None or _as_date(record["date"]) <= query.end_date)
        ]
        if query.adjusted and is_intraday_interval(interval):
            return await self._adjust_intraday_prices(query.symbol, filtered)
        return filtered

    async def fetch_equity_search(self, query: str, is_symbol: bool | None = None) -> list[dict[str, Any]]:
        keyword = _to_tdx_search_keyword(query, is_symbol)
        if keyword is None:
            return []
        payload = await self._get("/api/search", {"keyword": keyword})
        items = _response_data(payload)
        if not isinstance(items, list):
            return []

        query_text = query.strip().upper()
        plain_query = cn_plain_symbol(query_text)
        results: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code", "")).strip()
            name = str(item.get("name", "")).strip()
            exchange = str(item.get("exchange", "")).strip().lower() or None
            if not code:
                continue
            symbol = to_openbb_symbol(f"{code}.{exchange}" if exchange else code)
            if is_symbol and not _symbol_matches(query_text, plain_query, code, symbol, exchange):
                continue
            results.append({"symbol": symbol, "name": name, "source": "tdx"})
        return results

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{self.base_url}{path}", params=params)
        if response.is_error:
            raise SourceError(f"TDX request failed: {response.status_code}")
        data = response.json()
        if not isinstance(data, dict):
            raise SourceError("TDX returned invalid JSON")
        return data

    async def _adjust_intraday_prices(self, symbol: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not records:
            return records
        factors = await self._fetch_adjust_factors(symbol, _as_date(records[0]["date"]), _as_date(records[-1]["date"]))
        if not factors:
            raise SourceError(f"TDX adjusted intraday prices require adjustment factors for {symbol}")
        return [_apply_adjust_factor(record, _factor_for_date(factors, _as_date(record["date"]))) for record in records]

    async def _fetch_adjust_factors(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[tuple[date, float]]:
        return await asyncio.to_thread(_fetch_baostock_adjust_factors, symbol, start_date, end_date)


def _response_data(payload: dict[str, Any]) -> Any:
    if payload.get("code") not in {0, None}:
        raise SourceError(str(payload.get("message") or "TDX request failed"))
    return payload.get("data")


def _to_tdx_code(symbol: str) -> str:
    code = cn_plain_symbol(symbol)
    if code is None:
        raise SourceError(f"TDX only supports China A-share symbols: {symbol}")
    return code


def _to_tdx_interval(interval: str) -> str:
    mapping = {
        "1m": "minute1",
        "5m": "minute5",
        "15m": "minute15",
        "30m": "minute30",
        "60m": "hour",
        "1h": "hour",
        "1d": "day",
        "1w": "week",
        "1M": "month",
    }
    normalized = normalize_interval(interval)
    if normalized not in mapping:
        raise SourceError(f"TDX unsupported interval: {interval}")
    return mapping[normalized]


def _to_tdx_kline_path(interval: str, adjusted: bool) -> str:
    if not adjusted:
        return "/api/kline-all/tdx"
    if is_intraday_interval(interval):
        return "/api/kline-all/tdx"
    return "/api/kline-all/ths"


def _to_tdx_search_keyword(query: str, is_symbol: bool | None) -> str | None:
    text = query.strip()
    upper = text.upper()
    plain = cn_plain_symbol(upper)
    if plain is not None:
        return plain if is_symbol else text
    code, suffix = split_symbol(upper)
    if suffix is not None:
        return None
    if code.isdigit() and len(code) != 6:
        return None
    if code.isascii() and code.isalpha():
        return None
    return text


def _normalize_quote(item: dict[str, Any], symbol: str) -> dict[str, Any]:
    kline = item.get("K") if isinstance(item.get("K"), dict) else {}
    prev_close = _price(kline.get("Last"))
    last_price = _price(kline.get("Close"))
    change = (
        last_price - prev_close
        if last_price is not None and prev_close not in {None, 0}
        else None
    )
    return {
        "symbol": to_openbb_symbol(symbol),
        "last_price": last_price,
        "open": _price(kline.get("Open")),
        "high": _price(kline.get("High")),
        "low": _price(kline.get("Low")),
        "prev_close": prev_close,
        "volume": _optional_float(item.get("TotalHand"), multiplier=100),
        "change": change,
        "change_percent": (change / prev_close * 100) if change is not None and prev_close else None,
        "source": "tdx",
    }


def _normalize_price_row(row: dict[str, Any], symbol: str) -> dict[str, Any]:
    return {
        "symbol": to_openbb_symbol(symbol),
        "date": _parse_date(row.get("Time")),
        "open": _price(row.get("Open")),
        "high": _price(row.get("High")),
        "low": _price(row.get("Low")),
        "close": _price(row.get("Close")),
        "volume": _optional_float(row.get("Volume"), multiplier=100),
        "amount": _price(row.get("Amount")),
        "source": "tdx",
    }


def _fetch_baostock_adjust_factors(
    symbol: str,
    start_date: date,
    end_date: date,
) -> list[tuple[date, float]]:
    import baostock as bs

    from openbb_finance.sources.baostock import _baostock_session, _to_baostock_symbol

    with _baostock_session(bs):
        rs = bs.query_adjust_factor(
            _to_baostock_symbol(symbol),
            start_date=ADJUST_FACTOR_START_DATE.isoformat(),
            end_date=end_date.isoformat(),
        )
        if rs.error_code != "0":
            raise SourceError(rs.error_msg)
        rows = []
        while rs.next():
            rows.append(dict(zip(rs.fields, rs.get_row_data(), strict=True)))
    return _normalize_adjust_factors(rows)


def _normalize_adjust_factors(rows: list[dict[str, str]]) -> list[tuple[date, float]]:
    factors: list[tuple[date, float]] = []
    for row in rows:
        raw_date = row.get("dividOperateDate") or row.get("date")
        raw_factor = row.get("foreAdjustFactor") or row.get("adjustFactor")
        if not raw_date or raw_factor in {None, ""}:
            continue
        factors.append((date.fromisoformat(raw_date), float(raw_factor)))
    return sorted(factors, key=lambda item: item[0])


def _factor_for_date(factors: list[tuple[date, float]], value: date) -> float:
    selected = factors[0][1]
    for factor_date, factor in factors:
        if factor_date > value:
            break
        selected = factor
    return selected


def _apply_adjust_factor(record: dict[str, Any], factor: float) -> dict[str, Any]:
    adjusted = dict(record)
    for field in ("open", "high", "low", "close"):
        value = adjusted.get(field)
        if value is not None:
            adjusted[field] = round(float(value) * factor, 6)
    return adjusted


def _parse_date(value: Any) -> datetime:
    text = str(value or "")
    if not text:
        raise SourceError("TDX returned price row without Time")
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _as_date(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def _price(value: Any) -> float | None:
    result = _optional_float(value, multiplier=0.001)
    return round(result, 6) if result is not None else None


def _optional_float(value: Any, *, multiplier: float = 1.0) -> float | None:
    if value in {None, ""}:
        return None
    return float(value) * multiplier


def _symbol_matches(
    query: str,
    plain_query: str | None,
    code: str,
    symbol: str,
    exchange: str | None,
) -> bool:
    requested_exchange = cn_exchange(query)
    if requested_exchange is not None and exchange is not None and exchange != requested_exchange:
        return False
    return query in code.upper() or query in symbol.upper() or (plain_query is not None and plain_query in code)
