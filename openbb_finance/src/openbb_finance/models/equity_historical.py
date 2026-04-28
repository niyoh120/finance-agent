"""Equity historical prices with routed data sources."""

from __future__ import annotations

from datetime import date as dateType
from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.equity_historical import (
    EquityHistoricalData,
    EquityHistoricalQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.registry import build_default_registry
from openbb_finance.router import route_price_sources
from openbb_finance.sources.base import PriceQuery, infer_market


class FinanceEquityHistoricalQueryParams(EquityHistoricalQueryParams):
    """Finance equity historical price query."""

    interval: str = Field(default="1d", description="Price interval, e.g. 1d, 1w, 1M, 5m, 15m, 30m, 60m.")
    adjusted: bool = Field(default=False, description="Whether to request adjusted prices.")


class FinanceEquityHistoricalData(EquityHistoricalData):
    """Finance historical price data."""

    symbol: str | None = Field(default=None, description="Requested symbol.")
    source: str | None = Field(default=None, description="Selected data source.")


class FinanceEquityHistoricalFetcher(
    Fetcher[FinanceEquityHistoricalQueryParams, list[FinanceEquityHistoricalData]]
):
    """Fetcher for routed historical price data."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceEquityHistoricalQueryParams:
        return FinanceEquityHistoricalQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceEquityHistoricalQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials
        registry = kwargs.get("registry") or build_default_registry()
        market = infer_market(query.symbol)
        price_query = PriceQuery(
            symbol=query.symbol,
            market=market,
            start_date=query.start_date,
            end_date=query.end_date,
            interval=query.interval,
            adjusted=query.adjusted,
        )
        for source in registry.ordered_by_names(route_price_sources(price_query)):
            if not hasattr(source, "fetch_price"):
                continue
            try:
                return await source.fetch_price(price_query)
            except Exception:
                continue
        return []

    @staticmethod
    def transform_data(
        query: FinanceEquityHistoricalQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceEquityHistoricalData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [
            FinanceEquityHistoricalData(
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


def _to_date(value: Any) -> dateType:
    if isinstance(value, dateType):
        return value
    return dateType.fromisoformat(str(value)[:10])
