"""ETF historical prices with routed data sources."""

from __future__ import annotations

from datetime import date as dateType
from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.etf_historical import EtfHistoricalData, EtfHistoricalQueryParams
from openbb_core.provider.utils.errors import EmptyDataError

from openbb_finance.registry import build_default_registry
from openbb_finance.router import route_price_sources
from openbb_finance.sources.base import PriceQuery, infer_market


class FinanceEtfHistoricalFetcher(Fetcher[EtfHistoricalQueryParams, list[EtfHistoricalData]]):
    """Fetcher for routed ETF historical price data."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> EtfHistoricalQueryParams:
        return EtfHistoricalQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: EtfHistoricalQueryParams,
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
            interval="1d",
        )
        for source in registry.ordered_by_names(route_price_sources(price_query)):
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
        query: EtfHistoricalQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[EtfHistoricalData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [
            EtfHistoricalData(
                date=_to_date(row["date"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=row.get("volume"),
            )
            for row in data
        ]


def _to_date(value: Any) -> dateType:
    if isinstance(value, dateType):
        return value
    return dateType.fromisoformat(str(value)[:10])
