"""Index search with routed data sources."""

from __future__ import annotations

from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.index_search import (
    IndexSearchData,
    IndexSearchQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.registry import build_default_registry


class FinanceIndexSearchData(IndexSearchData):
    """Finance index search data."""

    source: str | None = Field(default=None, description="Selected data source.")


class FinanceIndexSearchFetcher(Fetcher[IndexSearchQueryParams, list[FinanceIndexSearchData]]):
    """Fetcher for index search data."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> IndexSearchQueryParams:
        return IndexSearchQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: IndexSearchQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials
        registry = kwargs.get("registry") or build_default_registry()
        for source in registry.ordered_by_names(["eastmoney"]):
            if not hasattr(source, "fetch_index_search"):
                continue
            try:
                results = await source.fetch_index_search(query.query, query.is_symbol)
                if results:
                    return results
            except Exception:
                continue
        return []

    @staticmethod
    def transform_data(
        query: IndexSearchQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceIndexSearchData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceIndexSearchData.model_validate(item) for item in data]
