"""AKShare data source."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import pandas as pd

from openbb_finance.config import SourceConfig
from openbb_finance.sources.base import (
    DataType,
    Market,
    PriceQuery,
    SourceError,
    is_intraday_interval,
    normalize_interval,
)


class AkshareSource:
    name = "akshare"

    def __init__(self, config: SourceConfig) -> None:
        self.enabled = config.enabled
        self.priority = config.priority

    def supports(self, market: Market, data_type: DataType, **kwargs: Any) -> bool:
        del kwargs
        return market == "cn" and data_type in {"price", "news", "calendar", "fundamental", "macro"}

    async def fetch_equity_search(self, query: str, is_symbol: bool | None = None) -> list[dict[str, Any]]:
        import akshare as ak

        df = await asyncio.to_thread(ak.stock_info_a_code_name)
        if df.empty:
            return []
        data = df.rename(columns={"code": "symbol", "name": "name", "代码": "symbol", "名称": "name"})
        text = query.strip().upper()
        results: list[dict[str, Any]] = []
        for _, row in data.iterrows():
            symbol = str(row.get("symbol", "")).strip()
            name = str(row.get("name", "")).strip()
            if is_symbol:
                matched = text in symbol.upper()
            else:
                matched = text in symbol.upper() or text in name.upper()
            if matched:
                results.append({"symbol": _to_openbb_symbol(symbol), "name": name, "source": "akshare"})
        return results

    async def fetch_quote(self, symbol: str) -> dict[str, Any]:
        import akshare as ak

        plain = _to_plain_symbol(symbol)
        df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
        data = df.rename(
            columns={
                "代码": "symbol",
                "名称": "name",
                "最新价": "last_price",
                "今开": "open",
                "最高": "high",
                "最低": "low",
                "昨收": "prev_close",
                "成交量": "volume",
                "涨跌额": "change",
                "涨跌幅": "change_percent",
            }
        )
        matched = data[data["symbol"].astype(str) == plain]
        if matched.empty:
            raise SourceError("AKShare quote returned empty data")
        row = matched.iloc[0]
        return {
            "symbol": _to_openbb_symbol(plain),
            "name": row.get("name"),
            "last_price": _optional_float(row.get("last_price")),
            "open": _optional_float(row.get("open")),
            "high": _optional_float(row.get("high")),
            "low": _optional_float(row.get("low")),
            "prev_close": _optional_float(row.get("prev_close")),
            "volume": _optional_float(row.get("volume")),
            "change": _optional_float(row.get("change")),
            "change_percent": _optional_float(row.get("change_percent")),
            "source": "akshare",
        }

    async def fetch_price(self, query: PriceQuery) -> list[dict[str, Any]]:
        import akshare as ak

        interval = normalize_interval(query.interval)
        symbol = _to_plain_symbol(query.symbol)
        if is_intraday_interval(interval):
            period = interval.removesuffix("m").replace("1h", "60")
            df = await asyncio.to_thread(ak.stock_zh_a_hist_min_em, symbol=symbol, period=period, adjust="")
        else:
            period = {"1d": "daily", "1w": "weekly", "1M": "monthly"}.get(interval, "daily")
            df = await asyncio.to_thread(
                ak.stock_zh_a_hist,
                symbol=symbol,
                period=period,
                start_date=query.start_date.strftime("%Y%m%d") if query.start_date else "19700101",
                end_date=query.end_date.strftime("%Y%m%d") if query.end_date else "20500101",
                adjust="qfq" if query.adjusted else "",
            )
        return _normalize_dataframe(df, query.symbol)


def _to_plain_symbol(symbol: str) -> str:
    return symbol.strip().upper().split(".")[0]


def _to_openbb_symbol(symbol: str) -> str:
    code = symbol.strip().upper().split(".")[0]
    if code.startswith("6"):
        return f"{code}.XSHG"
    return f"{code}.XSHE"


def _normalize_dataframe(df: pd.DataFrame, symbol: str) -> list[dict[str, Any]]:
    if df.empty:
        raise SourceError("AKShare returned empty data")
    rename = {
        "日期": "date",
        "时间": "date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "成交额": "amount",
    }
    data = df.rename(columns=rename)
    rows: list[dict[str, Any]] = []
    for _, row in data.iterrows():
        date_value = row.get("date")
        parsed = pd.to_datetime(date_value).to_pydatetime()
        rows.append(
            {
                "symbol": symbol,
                "date": parsed.date() if isinstance(parsed, datetime) else parsed,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": _optional_float(row.get("volume")),
                "amount": _optional_float(row.get("amount")),
                "source": "akshare",
            }
        )
    return rows


def _optional_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)
