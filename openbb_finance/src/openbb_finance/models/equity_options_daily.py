"""Single-day option contract OHLCV from ConvexValue /mas/open-close."""

from __future__ import annotations

from datetime import date as dateType
from datetime import datetime
from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.equity_historical import (
    EquityHistoricalData,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.models._query_coerce import ConvexValueQueryParams
from openbb_finance.sources import convexvalue as cv


class FinanceOptionDailyQueryParams(ConvexValueQueryParams):
    """Option contract single-day OHLCV query.

    symbol is the OCC-style option ticker; start_date/end_date are ignored —
    the underlying CV endpoint takes one trading day. We read `date` from
    start_date if provided, otherwise fall back to end_date.
    """

    symbol: str = Field(description=QUERY_DESCRIPTIONS.get("symbol", ""))
    start_date: str | None = Field(default=None)
    end_date: str | None = Field(default=None)
    date: str | None = Field(
        default=None,
        description="Trading day YYYY-MM-DD. Defaults to start_date or end_date.",
    )


class FinanceOptionDailyData(EquityHistoricalData):
    """Option contract single-day bar."""

    symbol: str | None = Field(default=None)
    pre_market: float | None = Field(default=None, description="Pre-market price.")
    after_hours: float | None = Field(default=None, description="After-hours price.")


class FinanceOptionDailyFetcher(
    Fetcher[FinanceOptionDailyQueryParams, list[FinanceOptionDailyData]]
):
    """Fetcher for ConvexValue option single-day open/close."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceOptionDailyQueryParams:
        merged: dict[str, Any] = dict(params)
        for key in ("date", "start_date", "end_date"):
            value = merged.get(key)
            # ConvexValueQueryParams strips Query() markers via before-validator,
            # but transform_query may run before that; drop them here too.
            if type(value).__name__ == "Query":
                merged.pop(key)
                continue
            if value is not None:
                merged[key] = _iso(value)
        if not merged.get("date"):
            merged["date"] = merged.get("start_date") or merged.get("end_date")
        return FinanceOptionDailyQueryParams(**merged)

    @staticmethod
    async def aextract_data(
        query: FinanceOptionDailyQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        del credentials, kwargs
        if not query.date:
            raise ValueError("date, start_date, or end_date is required for option daily data")
        return await cv.fetch_option_open_close(query.symbol, query.date)

    @staticmethod
    def transform_data(
        query: FinanceOptionDailyQueryParams,
        data: dict[str, Any] | None,
        **kwargs: Any,
    ) -> list[FinanceOptionDailyData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceOptionDailyData(
            symbol=data.get("symbol"),
            date=_parse_date(data.get("from") or data.get("date")),
            open=_num(data.get("open")),
            high=_num(data.get("high")),
            low=_num(data.get("low")),
            close=_num(data.get("close")),
            volume=_num(data.get("volume")),
            pre_market=_num(data.get("preMarket")),
            after_hours=_num(data.get("afterHours")),
        )]


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return getattr(value, "isoformat", lambda: str(value))()


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> dateType | datetime | None:
    if value is None:
        return None
    text = str(value)
    try:
        return dateType.fromisoformat(text[:10])
    except ValueError:
        return None
