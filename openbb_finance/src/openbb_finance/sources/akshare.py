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
from openbb_finance.sources.symbols import (
    cn_plain_symbol,
    futures_exchange,
    futures_plain_code,
    to_openbb_symbol,
)


class AkshareSource:
    name = "akshare"

    def __init__(self, config: SourceConfig) -> None:
        self.enabled = config.enabled

    def supports(self, market: Market, data_type: DataType, **kwargs: Any) -> bool:
        del kwargs
        supported_types = {"price", "news", "calendar", "fundamental", "macro", "search"}
        return market in {"cn", "future"} and data_type in supported_types

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

    async def fetch_futures_price(self, query: PriceQuery) -> list[dict[str, Any]]:
        """Sina futures daily history: main continuous <CODE>0, month <CODE><YYMM>.

        Covers the five domestic commodity exchanges (SHFE/DCE/CZCE/CFFEX/GFEX).
        SGE spot-deferred products are not exposed by the sina daily endpoint, so
        they stay on the tdx source. Unlisted month contracts raise from the
        underlying endpoint and are caught by the fetcher's fallback loop.
        """
        import akshare as ak

        exchange = futures_exchange(query.symbol)
        if query.market != "future" or exchange is None:
            raise SourceError(f"AKShare futures price requires a futures symbol: {query.symbol}")
        if exchange == "SGE":
            raise SourceError(f"AKShare does not cover SGE spot-deferred products: {query.symbol}")
        code = futures_plain_code(query.symbol)
        if query.expiration:
            year, month = _parse_futures_expiration(query.expiration)
            symbol = f"{code}{year}{month:02d}"
        else:
            symbol = f"{code}0"
        df = await asyncio.to_thread(ak.futures_zh_daily_sina, symbol=symbol)
        return _normalize_futures_daily(df, query.symbol)

    async def fetch_futures_search(self, query: str, is_symbol: bool | None = None) -> list[dict[str, Any]]:
        """Search futures contracts via akshare.

        futures_symbol_mark maps product Chinese names to sina mark codes; matched
        products are expanded through futures_zh_realtime into per-contract rows.
        is_symbol=True matches the mark code prefix (e.g. si -> 工业硅, si.GFEX);
        otherwise the query matches the Chinese product name (e.g. 工业硅).
        """
        import akshare as ak

        mark_df = await asyncio.to_thread(ak.futures_symbol_mark)
        if mark_df.empty:
            return []
        text = query.strip().upper()
        plain_text = text.partition(".")[0]
        products: list[tuple[str, str]] = []
        for _, row in mark_df.iterrows():
            mark = str(row.get("mark") or "").strip()
            chinese = str(row.get("symbol") or "").strip()
            if not mark or not chinese:
                continue
            prefix = mark.split("_", 1)[0].upper()
            if is_symbol:
                matched = text in {prefix, mark.upper()} or plain_text == prefix
            else:
                matched = text in chinese.upper()
            if matched:
                products.append((prefix, chinese))
        results: list[dict[str, Any]] = []
        for _prefix, chinese in products:
            try:
                df = await asyncio.to_thread(ak.futures_zh_realtime, symbol=chinese)
            except Exception:
                continue
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                code = str(row.get("symbol") or "").strip().upper()
                exchange = str(row.get("exchange") or "").strip().lower()
                if not code or not exchange:
                    continue
                symbol, expiration = _akshare_contract_symbol(exchange, code)
                results.append(
                    {
                        "symbol": symbol,
                        "expiration": expiration,
                        "code": code,
                        "name": str(row.get("name") or "").strip(),
                        "exchange": exchange.upper(),
                        "source": "akshare",
                    }
                )
        return results

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
            results.append(
                {
                    "date": date_val,
                    "symbol": "GDP",
                    "symbol_root": "GDP",
                    "country": "china",
                    "value": _optional_float(row.get("国内生产总值-绝对值", row.get("GDP"))),
                    "source": "akshare",
                }
            )
        return results

    async def fetch_macro_gdp_yearly(self) -> list[dict[str, Any]]:
        """Fetch China GDP yearly rate from AKShare."""
        import akshare as ak

        df = await asyncio.to_thread(ak.macro_china_gdp_yearly)
        if df.empty:
            return []

        results: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            results.append(
                {
                    "date": _normalize_macro_date(row.get("日期", "")),
                    "symbol": "GDP_YOY",
                    "symbol_root": "GDP",
                    "country": "china",
                    "value": _optional_float(row.get("今值")),
                    "consensus": _optional_float(row.get("预测值")),
                    "previous": _optional_float(row.get("前值")),
                    "source": "akshare",
                }
            )
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
            results.append(
                {
                    "date": date_val,
                    "symbol": "CPI",
                    "symbol_root": "CPI",
                    "country": "china",
                    "value": _optional_float(row.get(primary_column, row.get(fallback_column))),
                    "source": "akshare",
                }
            )
        return results

    async def fetch_macro_cpi_yearly(self) -> list[dict[str, Any]]:
        """Fetch China CPI yearly rate from AKShare."""
        import akshare as ak

        df = await asyncio.to_thread(ak.macro_china_cpi_yearly)
        if df.empty:
            return []

        results: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            results.append(
                {
                    "date": _normalize_macro_date(row.get("日期", "")),
                    "symbol": "CPI_YOY",
                    "symbol_root": "CPI",
                    "country": "china",
                    "value": _optional_float(row.get("今值")),
                    "consensus": _optional_float(row.get("预测值")),
                    "previous": _optional_float(row.get("前值")),
                    "source": "akshare",
                }
            )
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
            results.append(
                {
                    "date": date_val,
                    "symbol": "PPI",
                    "symbol_root": "PPI",
                    "country": "china",
                    "value": _optional_float(row.get("当月", row.get("当月同比"))),
                    "source": "akshare",
                }
            )
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
            results.append(
                {
                    "date": date_val,
                    "symbol": "PMI",
                    "symbol_root": "PMI",
                    "country": "china",
                    "value": _optional_float(row.get("制造业-指数", row.get("制造业"))),
                    "source": "akshare",
                }
            )
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


def _parse_futures_expiration(expiration: str) -> tuple[str, int]:
    """Parse YYYY-MM into (YY, month), e.g. 2026-10 -> ("26", 10)."""
    year, month = expiration.split("-", 1)
    return year[-2:], int(month)


def _akshare_contract_symbol(exchange: str, code: str) -> tuple[str, str | None]:
    """Map a sina realtime contract code to (user symbol, expiration YYYY-MM | None).

    Sina codes are <CODE>0 for main continuous and <CODE><YYMM> for month
    contracts; the realtime exchange column already matches our short codes
    (shfe/dce/czce/cffex/gfex).
    """
    upper = code.upper()
    exchange_upper = exchange.upper()
    if len(upper) > 1 and upper.endswith("0") and upper[:-1].isalpha():
        return f"{upper[:-1]}.{exchange_upper}", None
    if len(upper) >= 5 and upper[-4:].isdigit():
        return f"{upper[:-4]}.{exchange_upper}", f"20{upper[-4:-2]}-{upper[-2:]}"
    return f"{upper}.{exchange_upper}", None


def _normalize_futures_daily(df: pd.DataFrame, symbol: str) -> list[dict[str, Any]]:
    if df is None or df.empty:
        raise SourceError("AKShare futures returned empty data")
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        date_value = pd.to_datetime(row.get("date")).date()
        rows.append(
            {
                "symbol": symbol.strip().upper(),
                "date": date_value,
                "open": _optional_float(row.get("open")),
                "high": _optional_float(row.get("high")),
                "low": _optional_float(row.get("low")),
                "close": _optional_float(row.get("close")),
                "volume": _optional_float(row.get("volume")),
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
