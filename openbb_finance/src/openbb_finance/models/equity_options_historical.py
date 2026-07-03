"""Option contract historical OHLCV bars from ConvexValue /mas/aggs.

Treats an option contract (e.g. O:SPY260731C00750000) as an equity symbol,
inheriting the standard EquityHistorical model. CV's Massive Aggregates
returns {o,h,l,c,v,n,t,vw}; we map those to the openbb field names.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.equity_historical import (
    EquityHistoricalData,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.models._query_coerce import ConvexValueQueryParams
from openbb_finance.sources import convexvalue as cv


class FinanceOptionHistoricalQueryParams(ConvexValueQueryParams):
    """Option contract bars query.

    symbol is the OCC-style option ticker (e.g. O:SPY260731C00750000).
    """

    symbol: str = Field(description=QUERY_DESCRIPTIONS.get("symbol", ""))
    start_date: str | None = Field(default=None)
    end_date: str | None = Field(default=None)
    multiplier: int = Field(default=1, ge=1, description="Bar multiplier (e.g. 1, 5).")
    timespan: Literal[
        "second", "minute", "hour", "day", "week", "month", "quarter", "year"
    ] = Field(
        default="day",
        description="Bar timespan: second|minute|hour|day|week|month|quarter|year.",
    )


class FinanceOptionHistoricalData(EquityHistoricalData):
    """Option contract OHLCV bar."""

    symbol: str | None = Field(default=None, description="Option contract ticker.")
    transactions: int | None = Field(default=None, description="Trade count (CV n).")


class FinanceOptionHistoricalFetcher(
    Fetcher[FinanceOptionHistoricalQueryParams, list[FinanceOptionHistoricalData]]
):
    """Fetcher for ConvexValue option aggregate bars."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceOptionHistoricalQueryParams:
        return FinanceOptionHistoricalQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceOptionHistoricalQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials, kwargs
        date_from = _iso(query.start_date)
        date_to = _iso(query.end_date)
        if not date_from or not date_to:
            raise ValueError("start_date and end_date are required for option historical data")
        raw = await cv.fetch_option_aggregates(
            ticker=query.symbol,
            multiplier=query.multiplier,
            timespan=query.timespan,
            date_from=date_from,
            date_to=date_to,
        )
        results = raw.get("results", [])
        return [
            {
                "symbol": raw.get("ticker"),
                "date": _ms_to_datetime(bar.get("t")),
                "open": bar.get("o"),
                "high": bar.get("h"),
                "low": bar.get("l"),
                "close": bar.get("c"),
                "volume": bar.get("v"),
                "vwap": bar.get("vw"),
                "transactions": bar.get("n"),
            }
            for bar in results
        ]

    @staticmethod
    def transform_data(
        query: FinanceOptionHistoricalQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceOptionHistoricalData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceOptionHistoricalData.model_validate(row) for row in data]


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    # date or datetime
    return getattr(value, "isoformat", lambda: str(value))()


def _ms_to_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000.0, tz=timezone.utc)
    except (TypeError, OSError, OverflowError, ValueError):
        return None
