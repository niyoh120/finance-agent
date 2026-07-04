"""BaoStock data source."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from typing import Any

from openbb_finance.config import SourceConfig
from openbb_finance.sources.base import (
    DataType,
    Market,
    PriceQuery,
    SourceError,
    is_intraday_interval,
    normalize_interval,
)


class BaostockSource:
    name = "baostock"

    def __init__(self, config: SourceConfig) -> None:
        self.enabled = config.enabled

    def supports(self, market: Market, data_type: DataType, **kwargs: Any) -> bool:
        del kwargs
        return market == "cn" and data_type in {"price", "fundamental", "macro"}

    async def fetch_price(self, query: PriceQuery) -> list[dict[str, Any]]:
        import baostock as bs

        code = _to_baostock_symbol(query.symbol)
        interval = normalize_interval(query.interval)
        fields = (
            "date,time,open,high,low,close,volume,amount"
            if is_intraday_interval(interval)
            else "date,open,high,low,close,volume,amount"
        )

        with _baostock_session(bs):
            rs = bs.query_history_k_data_plus(
                code,
                fields,
                start_date=query.start_date.isoformat() if query.start_date else "",
                end_date=query.end_date.isoformat() if query.end_date else "",
                frequency=_to_frequency(query.interval),
                adjustflag="2" if query.adjusted else "3",
            )
            if rs.error_code != "0":
                raise SourceError(rs.error_msg)
            rows = []
            while rs.next():
                rows.append(dict(zip(rs.fields, rs.get_row_data(), strict=True)))

        return [_normalize_price_row(row, query.symbol) for row in rows]


@contextmanager
def _baostock_session(bs: Any):
    login = bs.login()
    if login.error_code != "0":
        raise SourceError(login.error_msg)
    try:
        yield
    finally:
        bs.logout()


def _to_baostock_symbol(symbol: str) -> str:
    value = symbol.strip().lower()
    if value.startswith(("sh.", "sz.")):
        return value

    code = value.split(".")[0]
    suffix = value.split(".")[1] if "." in value else None

    if suffix in ("xshg", "sh", "ss"):
        return f"sh.{code}"
    if suffix in ("xshe", "sz"):
        return f"sz.{code}"

    if code.startswith("399"):
        return f"sz.{code}"
    if code.startswith("6"):
        return f"sh.{code}"
    return f"sz.{code}"


def _to_frequency(interval: str) -> str:
    normalized = normalize_interval(interval)
    mapping = {
        "1d": "d",
        "1w": "w",
        "1M": "m",
        "5m": "5",
        "15m": "15",
        "30m": "30",
        "60m": "60",
        "1h": "60",
    }
    if normalized not in mapping:
        raise SourceError(f"BaoStock unsupported interval: {interval}")
    return mapping[normalized]


def _normalize_price_row(row: dict[str, str], symbol: str) -> dict[str, Any]:
    raw_time = row.get("time") or ""
    raw_date = row.get("date") or raw_time[:8]
    if raw_time:
        parsed_date: date | datetime = datetime.strptime(raw_time[:14], "%Y%m%d%H%M%S")
    elif raw_date and "-" not in raw_date:
        parsed_date = datetime.strptime(raw_date, "%Y%m%d").date()
    else:
        parsed_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
    return {
        "symbol": symbol,
        "date": parsed_date,
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": _optional_float(row.get("volume")),
        "amount": _optional_float(row.get("amount")),
        "source": "baostock",
    }


def _optional_float(value: str | None) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)
