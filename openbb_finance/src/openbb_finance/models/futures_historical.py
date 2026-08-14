"""Futures historical prices with routed data sources."""

from __future__ import annotations

from datetime import date as dateType
from datetime import datetime
from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.futures_historical import (
    FuturesHistoricalData,
    FuturesHistoricalQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.registry import build_default_registry
from openbb_finance.router import route_futures_price_sources
from openbb_finance.sources.base import PriceQuery, infer_market


class FinanceFuturesHistoricalQueryParams(FuturesHistoricalQueryParams):
    """Finance futures historical price query.

    The standard model uppercases `symbol`, so user symbols are normalized
    (rb.SHFE -> RB.SHFE) before reaching the data sources.
    """

    interval: str = Field(default="1d", description="Price interval, e.g. 1d, 1w, 1M, 5m, 15m, 30m, 60m.")
    adjusted: bool = Field(default=False, description="Whether to request adjusted prices.")


class FinanceFuturesHistoricalData(FuturesHistoricalData):
    """Finance futures historical price data.

    Inherits FuturesHistoricalData (openbb-core >= 1.6.13 required: 1.4.0~1.6.9
    shipped a broken date validator bound to the symbol field).
    """

    symbol: str | None = Field(default=None, description="Requested symbol.")
    source: str | None = Field(default=None, description="Selected data source.")


class FinanceFuturesHistoricalFetcher(Fetcher[FinanceFuturesHistoricalQueryParams, list[FinanceFuturesHistoricalData]]):
    """Fetcher for routed futures historical price data."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceFuturesHistoricalQueryParams:
        return FinanceFuturesHistoricalQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceFuturesHistoricalQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials
        registry = kwargs.get("registry") or build_default_registry()
        price_query = PriceQuery(
            symbol=query.symbol,
            market=infer_market(query.symbol),
            start_date=query.start_date,
            end_date=query.end_date,
            interval=query.interval,
            adjusted=query.adjusted,
            expiration=query.expiration,
        )
        for source in registry.ordered_by_names(route_futures_price_sources(price_query)):
            if not hasattr(source, "fetch_price"):
                continue
            try:
                data = await source.fetch_price(price_query)
                if data:
                    return data
            except Exception:
                continue
        return []

    @staticmethod
    def transform_data(
        query: FinanceFuturesHistoricalQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceFuturesHistoricalData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [
            FinanceFuturesHistoricalData(
                date=_to_date(row["date"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=row.get("volume"),
                symbol=row.get("symbol"),
                source=row.get("source"),
            )
            for row in data
        ]


def _to_date(value: Any) -> dateType | datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, dateType):
        return value
    text = str(value)
    if "T" in text or " " in text:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    return dateType.fromisoformat(text[:10])
