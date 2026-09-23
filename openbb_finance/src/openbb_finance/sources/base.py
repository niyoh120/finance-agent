"""Base abstractions for pluggable finance data sources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Protocol

Market = Literal["cn", "us", "hk", "global", "future"]
DataType = Literal["price", "news", "calendar", "fundamental", "macro", "search"]


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
    # Include pre/post-market bars for intraday intervals (sources that support it,
    # e.g. Schwab needExtendedHoursData); ignored where meaningless (daily+ bars).
    extended: bool = False
    # Contract expiration in YYYY-MM form; None means the main continuous contract.
    expiration: str | None = None
    # Routed asset context for capability filtering ("index"/"etf"); sources
    # may reject asset-specific identities they cannot map (e.g. TDX refusing
    # an unmapped US index alias instead of serving stock-market bars).
    asset: str | None = None


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
    """True for minute-grained intervals.

    Month/quarter/year labels (``1M``, ``m``, ``1mo``, ``1Q``, ``1Y``) share
    letters with minute aliases, so they are excluded by their normalized
    labels before the suffix check; a bare lowercase comparison would
    misclassify ``1M`` as the 1-minute interval.
    """
    normalized = normalize_interval(interval)
    if normalized in {"1M", "1Q", "1Y", "1mo", "1y"}:
        return False
    lowered = normalized.lower()
    return lowered.endswith("m") or lowered in {"1", "5", "15", "30", "60", "1h"}


def normalize_interval(interval: str) -> str:
    """Canonicalize a user interval alias, keeping month/minute case distinct.

    Exact matches win (``"1M"`` stays monthly, ``"1m"`` stays minute); the
    lowercase fallback only applies when the input itself is lowercase or the
    lowercase form carries no minute ambiguity (``"D"`` -> ``"1d"``,
    ``"M"`` -> ``"1M"``). The previous unconditional lowercase fallback
    collapsed ``"1M"`` into ``"1m"`` and misrouted monthly requests to
    minute sources.
    """
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
    if interval in mapping:
        return mapping[interval]
    lowered = interval.lower()
    if lowered == "1m":
        # Case-sensitive pair: only a lowercase input resolves to minutes.
        return "1m" if interval == "1m" else "1M"
    return mapping.get(lowered, interval)
