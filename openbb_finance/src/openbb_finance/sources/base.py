"""Base abstractions for pluggable finance data sources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Protocol

Market = Literal["cn", "us", "hk", "global"]
DataType = Literal["price", "news", "calendar", "fundamental", "macro"]


@dataclass(frozen=True)
class DataSourceInfo:
    name: str
    enabled: bool


@dataclass(frozen=True)
class PriceQuery:
    symbol: str
    market: Market
    start_date: date | None = None
    end_date: date | None = None
    interval: str = "1d"
    adjusted: bool = False


class DataSource(Protocol):
    name: str
    enabled: bool

    def supports(self, market: Market, data_type: DataType, **kwargs: Any) -> bool: ...


class SourceError(RuntimeError):
    """Raised when a data source cannot fulfill a request."""


def infer_market(symbol: str) -> Market:
    from openbb_finance.sources.symbols import infer_market_from_symbol

    return infer_market_from_symbol(symbol)


def is_intraday_interval(interval: str) -> bool:
    normalized = interval.lower()
    return normalized.endswith("m") or normalized in {"1", "5", "15", "30", "60", "1h"}


def normalize_interval(interval: str) -> str:
    mapping = {
        "1": "1m",
        "5": "5m",
        "15": "15m",
        "30": "30m",
        "60": "60m",
        "d": "1d",
        "w": "1w",
        "m": "1M",
    }
    return mapping.get(interval, mapping.get(interval.lower(), interval))
