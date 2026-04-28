"""Equity search with routed data sources."""

from __future__ import annotations

from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.equity_search import EquitySearchData, EquitySearchQueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.registry import build_default_registry


class FinanceEquitySearchData(EquitySearchData):
    """Finance equity search data."""

    source: str | None = Field(default=None, description="Selected data source.")


class FinanceEquitySearchFetcher(Fetcher[EquitySearchQueryParams, list[FinanceEquitySearchData]]):
    """Fetcher for equity search data."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> EquitySearchQueryParams:
        return EquitySearchQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: EquitySearchQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials
        registry = kwargs.get("registry") or build_default_registry()
        for source in registry.ordered_by_names(["akshare"]):
            if not hasattr(source, "fetch_equity_search"):
                continue
            try:
                return await source.fetch_equity_search(query.query, query.is_symbol)
            except Exception:
                continue
        return []

    @staticmethod
    def transform_data(
        query: EquitySearchQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceEquitySearchData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceEquitySearchData.model_validate(item) for item in data]
