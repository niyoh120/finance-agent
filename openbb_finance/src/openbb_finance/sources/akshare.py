"""AKShare data source."""

from __future__ import annotations

import asyncio
from datetime import date, datetime
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
from openbb_finance.sources.symbols import cn_plain_symbol, to_openbb_symbol


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
        plain_query = cn_plain_symbol(text)
        results: list[dict[str, Any]] = []
        for _, row in data.iterrows():
            symbol = str(row.get("symbol", "")).strip()
            name = str(row.get("name", "")).strip()
            symbol_text = symbol.upper()
            if is_symbol:
                matched = (plain_query or text) in symbol_text
            else:
                matched = (
                    text in symbol_text
                    or (plain_query is not None and plain_query in symbol_text)
                    or text in name.upper()
                )
            if matched:
                results.append({"symbol": to_openbb_symbol(symbol), "name": name, "source": "akshare"})
        return results

    async def fetch_quote(self, symbol: str) -> dict[str, Any]:
        import akshare as ak

        plain = cn_plain_symbol(symbol)
        if plain is None:
            raise SourceError(f"AKShare quote only supports China A-share symbols: {symbol}")
        try:
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
            if not matched.empty:
                return _quote_from_spot_row(matched.iloc[0], plain)
        except Exception:
            pass

        return await asyncio.to_thread(_fetch_individual_quote, ak, plain)

    async def fetch_price(self, query: PriceQuery) -> list[dict[str, Any]]:
        import akshare as ak

        interval = normalize_interval(query.interval)
        symbol = cn_plain_symbol(query.symbol)
        if symbol is None:
            raise SourceError(f"AKShare price only supports China A-share symbols: {query.symbol}")
        if is_intraday_interval(interval):
            period = interval.removesuffix("m").replace("1h", "60")
            df = await asyncio.to_thread(
                ak.stock_zh_a_hist_min_em,
                symbol=symbol,
                period=period,
                adjust="qfq" if query.adjusted else "",
            )
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
        return _normalize_dataframe(df, query.symbol, preserve_datetime=is_intraday_interval(interval))

    async def fetch_macro_gdp(self) -> list[dict[str, Any]]:
        """Fetch China GDP quarterly data from AKShare."""
        import akshare as ak

        df = await asyncio.to_thread(ak.macro_china_gdp)
        if df.empty:
            return []
        
        results: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            date_val = _normalize_macro_date(row.get("季度", row.get("日期", "")))
            results.append({
                "date": date_val,
                "symbol": "GDP",
                "symbol_root": "GDP",
                "country": "china",
                "value": _optional_float(row.get("国内生产总值-绝对值", row.get("GDP"))),
                "source": "akshare",
            })
        return results

    async def fetch_macro_gdp_yearly(self) -> list[dict[str, Any]]:
        """Fetch China GDP yearly rate from AKShare."""
        import akshare as ak

        df = await asyncio.to_thread(ak.macro_china_gdp_yearly)
        if df.empty:
            return []
        
        results: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            results.append({
                "date": _normalize_macro_date(row.get("日期", "")),
                "symbol": "GDP_YOY",
                "symbol_root": "GDP",
                "country": "china",
                "value": _optional_float(row.get("今值")),
                "consensus": _optional_float(row.get("预测值")),
                "previous": _optional_float(row.get("前值")),
                "source": "akshare",
            })
        return results

    async def fetch_macro_cpi(self, transform: str = "index") -> list[dict[str, Any]]:
        """Fetch China CPI monthly data from AKShare."""
        import akshare as ak

        df = await asyncio.to_thread(ak.macro_china_cpi)
        if df.empty:
            return []

        value_columns = {
            "index": ("全国-当月", "全国当月"),
            "yoy": ("全国-同比增长", "全国同比增长"),
            "period": ("全国-环比增长", "全国环比增长"),
        }
        primary_column, fallback_column = value_columns.get(transform, value_columns["index"])
        results: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            date_val = _normalize_macro_date(row.get("月份", row.get("日期", "")))
            results.append({
                "date": date_val,
                "symbol": "CPI",
                "symbol_root": "CPI",
                "country": "china",
                "value": _optional_float(row.get(primary_column, row.get(fallback_column))),
                "source": "akshare",
            })
        return results

    async def fetch_macro_cpi_yearly(self) -> list[dict[str, Any]]:
        """Fetch China CPI yearly rate from AKShare."""
        import akshare as ak

        df = await asyncio.to_thread(ak.macro_china_cpi_yearly)
        if df.empty:
            return []
        
        results: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            results.append({
                "date": _normalize_macro_date(row.get("日期", "")),
                "symbol": "CPI_YOY",
                "symbol_root": "CPI",
                "country": "china",
                "value": _optional_float(row.get("今值")),
                "consensus": _optional_float(row.get("预测值")),
                "previous": _optional_float(row.get("前值")),
                "source": "akshare",
            })
        return results

    async def fetch_macro_ppi(self) -> list[dict[str, Any]]:
        """Fetch China PPI data from AKShare."""
        import akshare as ak

        df = await asyncio.to_thread(ak.macro_china_ppi)
        if df.empty:
            return []
        
        results: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            date_val = _normalize_macro_date(row.get("月份", row.get("日期", "")))
            results.append({
                "date": date_val,
                "symbol": "PPI",
                "symbol_root": "PPI",
                "country": "china",
                "value": _optional_float(row.get("当月", row.get("当月同比"))),
                "source": "akshare",
            })
        return results

    async def fetch_macro_pmi(self) -> list[dict[str, Any]]:
        """Fetch China PMI data from AKShare."""
        import akshare as ak

        df = await asyncio.to_thread(ak.macro_china_pmi)
        if df.empty:
            return []
        
        results: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            date_val = _normalize_macro_date(row.get("月份", row.get("日期", "")))
            results.append({
                "date": date_val,
                "symbol": "PMI",
                "symbol_root": "PMI",
                "country": "china",
                "value": _optional_float(row.get("制造业-指数", row.get("制造业"))),
                "source": "akshare",
            })
        return results

    async def fetch_macro_indicators(
        self, symbol: str, start_date: str | None = None, end_date: str | None = None
    ) -> list[dict[str, Any]]:
        """Fetch macroeconomic indicators by symbol."""
        symbol_upper = symbol.upper()
        
        if symbol_upper == "GDP":
            data = await self.fetch_macro_gdp()
        elif symbol_upper == "GDP_YOY":
            data = await self.fetch_macro_gdp_yearly()
        elif symbol_upper == "CPI":
            data = await self.fetch_macro_cpi()
        elif symbol_upper == "CPI_YOY":
            data = await self.fetch_macro_cpi_yearly()
        elif symbol_upper == "PPI":
            data = await self.fetch_macro_ppi()
        elif symbol_upper == "PMI":
            data = await self.fetch_macro_pmi()
        else:
            return []
        
        # Filter by date range if provided
        if start_date or end_date:
            filtered = []
            for item in data:
                item_date = _normalize_macro_date(item.get("date"))
                if start_date and item_date < start_date:
                    continue
                if end_date and item_date > end_date:
                    continue
                item = {**item, "date": item_date}
                filtered.append(item)
            return filtered
        
        return data


def _quote_from_spot_row(row: pd.Series, symbol: str) -> dict[str, Any]:
    return {
        "symbol": to_openbb_symbol(symbol),
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


def _fetch_individual_quote(ak: Any, symbol: str) -> dict[str, Any]:
    df = ak.stock_individual_info_em(symbol=symbol)
    if df.empty:
        raise SourceError("AKShare quote returned empty data")
    data = dict(zip(df["item"].astype(str), df["value"], strict=False))
    return {
        "symbol": to_openbb_symbol(symbol),
        "name": data.get("股票简称"),
        "last_price": _optional_float(data.get("最新")),
        "open": _optional_float(data.get("今开")),
        "high": _optional_float(data.get("最高")),
        "low": _optional_float(data.get("最低")),
        "prev_close": _optional_float(data.get("昨收")),
        "volume": _optional_float(data.get("成交量")),
        "change": _optional_float(data.get("涨跌额")),
        "change_percent": _optional_float(data.get("涨跌幅")),
        "source": "akshare",
    }


def _normalize_dataframe(df: pd.DataFrame, symbol: str, *, preserve_datetime: bool = False) -> list[dict[str, Any]]:
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
                "date": parsed if preserve_datetime else parsed.date() if isinstance(parsed, datetime) else parsed,
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


def _normalize_macro_date(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return text
    try:
        return pd.to_datetime(text).date().isoformat()
    except Exception:
        pass
    if "年" in text and "月" in text:
        year, month_text = text.split("年", 1)
        month = "".join(ch for ch in month_text if ch.isdigit())
        if year.isdigit() and month:
            return f"{int(year):04d}-{int(month):02d}-01"
    if "年" in text and "季度" in text:
        year, quarter_text = text.split("年", 1)
        if year.isdigit():
            quarter_digits = [ch for ch in quarter_text if ch.isdigit()]
            if quarter_digits:
                quarter = int(quarter_digits[-1])
                month_day = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}.get(quarter)
                if month_day:
                    return f"{int(year):04d}-{month_day}"
    if len(text) == 6 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-01"
    return text


def _optional_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)
