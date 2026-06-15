"""Equity quotes with routed data sources."""

from __future__ import annotations

from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.equity_quote import EquityQuoteData, EquityQuoteQueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.registry import build_default_registry
from openbb_finance.sources.base import infer_market


class FinanceEquityQuoteData(EquityQuoteData):
    """Finance equity quote data."""

    source: str | None = Field(default=None, description="Selected data source.")


class FinanceEquityQuoteFetcher(Fetcher[EquityQuoteQueryParams, list[FinanceEquityQuoteData]]):
    """Fetcher for routed equity quote data."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> EquityQuoteQueryParams:
        return EquityQuoteQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: EquityQuoteQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials
        registry = kwargs.get("registry") or build_default_registry()
        market = infer_market(query.symbol)
        names = ["tdx", "tickflow", "akshare"] if market == "cn" else ["tdx", "tickflow", "yahoo"]
        for source in registry.ordered_by_names(names):
            if not hasattr(source, "fetch_quote"):
                continue
            try:
                return [await source.fetch_quote(query.symbol)]
            except Exception:
                continue
        return []

    @staticmethod
    def transform_data(
        query: EquityQuoteQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceEquityQuoteData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceEquityQuoteData.model_validate(item) for item in data]
