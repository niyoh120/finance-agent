"""Sina quote data source."""

from __future__ import annotations

import re
from typing import Any, Literal

import httpx

from openbb_finance.config import SourceConfig
from openbb_finance.sources.base import DataType, Market, SourceError
from openbb_finance.sources.symbols import split_symbol


class SinaSource:
    """Sina quote API for index snapshots."""

    name = "sina"

    def __init__(self, config: SourceConfig) -> None:
        self.enabled = config.enabled
        self.priority = config.priority

    def supports(self, market: Market, data_type: DataType, **kwargs: Any) -> bool:
        del kwargs
        return market in {"cn", "us", "hk", "global"} and data_type == "index_snapshots"

    async def fetch_index_snapshots(
        self,
        region: Literal["cn", "us", "hk"],
        symbols: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        mappings = [_to_sina_symbol(symbol, region) for symbol in symbols or _default_symbols(region)]
        mappings = [(token, symbol) for token, symbol in mappings if token]
        if not mappings:
            return []

        url = f"https://hq.sinajs.cn/list={','.join(token for token, _ in mappings)}"
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
        if response.is_error:
            raise SourceError(f"Sina snapshots request failed: {response.status_code}")
        return _parse_response(response.text, dict(mappings))


def _default_symbols(region: str) -> list[str]:
    defaults = {
        "cn": ["000001.XSHG", "000016.XSHG", "000300.XSHG", "000905.XSHG", "399001.XSHE", "399006.XSHE"],
        "us": ["SPX", "DJI", "IXIC", "NDX"],
        "hk": ["HSI", "HSCEI", "HSTECH"],
    }
    return defaults.get(region, [])


def _to_sina_symbol(symbol: str, region: str) -> tuple[str, str]:
    value = symbol.strip().upper()
    if region == "cn":
        code, suffix = split_symbol(value)
        market = "sz" if suffix in {"SZ", "XSHE"} or code.startswith("399") else "sh"
        output = f"{code}.XSHE" if market == "sz" else f"{code}.XSHG"
        return f"{market}{code}", output
    if region == "hk":
        aliases = {"HSI": "rt_hkHSI", "HSCEI": "rt_hkHSCEI", "HSTECH": "rt_hkHSTECH"}
        return aliases.get(value, f"rt_hk{value}"), value
    aliases = {"SPX": "gb_$inx", "$INX": "gb_$inx", "INX": "gb_$inx", "DJI": "gb_dji", "IXIC": "gb_ixic", "NDX": "gb_ndx"}
    output = "SPX" if value in {"$INX", "INX"} else value
    return aliases.get(value, f"gb_{value.lower()}"), output


def _parse_response(text: str, symbols_by_token: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for token, raw_value in re.findall(r'var hq_str_([^=]+)="(.*?)";', text, flags=re.S):
        fields = raw_value.split(",")
        symbol = symbols_by_token.get(token)
        if not symbol or not fields or not fields[0]:
            continue
        if token.startswith(("sh", "sz")):
            row = _parse_cn(symbol, fields)
        elif token.startswith("rt_hk"):
            row = _parse_hk(symbol, fields)
        else:
            row = _parse_us(symbol, fields)
        if row:
            rows.append(row)
    return rows


def _parse_cn(symbol: str, fields: list[str]) -> dict[str, Any] | None:
    if len(fields) < 10:
        return None
    price = _float(fields[3])
    prev_close = _float(fields[2])
    change = price - prev_close if price is not None and prev_close is not None else None
    return {
        "symbol": symbol,
        "name": fields[0],
        "currency": "CNY",
        "price": price,
        "open": _float(fields[1]),
        "high": _float(fields[4]),
        "low": _float(fields[5]),
        "close": price,
        "volume": _int(fields[8]),
        "prev_close": prev_close,
        "change": change,
        "change_percent": (change / prev_close * 100) if change is not None and prev_close else None,
        "source": "sina",
    }


def _parse_hk(symbol: str, fields: list[str]) -> dict[str, Any] | None:
    if len(fields) < 13:
        return None
    return {
        "symbol": symbol,
        "name": fields[1],
        "currency": "HKD",
        "price": _float(fields[6]),
        "open": _float(fields[2]),
        "high": _float(fields[4]),
        "low": _float(fields[5]),
        "close": _float(fields[6]),
        "volume": _int(fields[12]),
        "prev_close": _float(fields[3]),
        "change": _float(fields[7]),
        "change_percent": _float(fields[8]),
        "source": "sina",
    }


def _parse_us(symbol: str, fields: list[str]) -> dict[str, Any] | None:
    if len(fields) < 11:
        return None
    return {
        "symbol": symbol,
        "name": fields[0],
        "currency": "USD",
        "price": _float(fields[1]),
        "open": _float(fields[5]),
        "high": _float(fields[6]),
        "low": _float(fields[7]),
        "close": _float(fields[1]),
        "volume": _int(fields[10]),
        "prev_close": _float(fields[26]) if len(fields) > 26 else None,
        "change": _float(fields[4]),
        "change_percent": _float(fields[2]),
        "source": "sina",
    }


def _float(value: str) -> float | None:
    if value in {"", "--"}:
        return None
    return float(value)


def _int(value: str) -> int | None:
    number = _float(value)
    return int(number) if number is not None else None
