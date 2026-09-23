"""ETF historical prices with routed data sources."""

from __future__ import annotations

import logging
from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.etf_historical import EtfHistoricalData, EtfHistoricalQueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field, field_validator

from openbb_finance.registry import build_default_registry
from openbb_finance.router import route_etf_price_sources
from openbb_finance.sources.base import PriceQuery, infer_market
from openbb_finance.sources.symbols import normalize_etf_symbol

from ._historical_query import is_minute_interval, normalize_query_interval, validate_intraday_rows

logger = logging.getLogger(__name__)


class FinanceEtfHistoricalQueryParams(EtfHistoricalQueryParams):
    """Finance ETF historical price query.

    Symbols are canonicalized with ETF asset context (bare CN codes keep their
    market inference; unknown suffixes fail); ``interval`` defaults to the
    historical daily behaviour and unlocks the routed minute chain
    (``1m``..``60m``, plus US-only ``10m``).
    """

    interval: str = Field(default="1d", description="Price interval, e.g. 1d, 1w, 1M, 1m, 5m, 15m, 30m, 60m.")

    @field_validator("symbol", mode="before", check_fields=False)
    @classmethod
    def _normalize_symbol(cls, v: str) -> str:
        return normalize_etf_symbol(v)

    @field_validator("interval", mode="before", check_fields=False)
    @classmethod
    def _normalize_interval(cls, v: str, info: Any) -> str:
        symbol = str((info.data or {}).get("symbol") or "")
        return normalize_query_interval(v, market=infer_market(symbol))


class FinanceEtfHistoricalFetcher(Fetcher[FinanceEtfHistoricalQueryParams, list[EtfHistoricalData]]):
    """Fetcher for routed ETF historical price data."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceEtfHistoricalQueryParams:
        return FinanceEtfHistoricalQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceEtfHistoricalQueryParams,
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
            asset="etf",
        )
        minute = is_minute_interval(query.interval)
        for source in registry.ordered_by_names(route_etf_price_sources(price_query)):
            if not hasattr(source, "fetch_price"):
                continue
            try:
                data = await source.fetch_price(price_query)
            except Exception:
                continue
            if not data:
                continue
            if minute:
                try:
                    validate_intraday_rows(data, symbol=query.symbol, interval=query.interval)
                except ValueError as exc:
                    logger.warning("Skipping %s minute result for %s: %s", source.name, query.symbol, exc)
                    continue
            return data
        return []

    @staticmethod
    def transform_data(
        query: FinanceEtfHistoricalQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[EtfHistoricalData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        # Raw date passthrough: the standard model validator keeps datetimes
        # (minute bars, with their source-side time-of-day) and dates (daily).
        return [
            EtfHistoricalData(
                date=row["date"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=row.get("volume"),
            )
            for row in data
        ]
