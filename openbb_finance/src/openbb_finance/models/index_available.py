"""Index available with routed data sources."""

from __future__ import annotations

from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.available_indices import (
    AvailableIndicesData,
    AvailableIndicesQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.registry import build_default_registry


class FinanceAvailableIndicesData(AvailableIndicesData):
    """Finance available indices data."""

    source: str | None = Field(default=None, description="Selected data source.")


class FinanceAvailableIndicesFetcher(Fetcher[AvailableIndicesQueryParams, list[FinanceAvailableIndicesData]]):
    """Fetcher for available indices data."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> AvailableIndicesQueryParams:
        return AvailableIndicesQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: AvailableIndicesQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials, query
        registry = kwargs.get("registry") or build_default_registry()
        # Use index_search to get available indices
        # Search for common terms to get a list of indices
        for source in registry.ordered_by_names(["eastmoney"]):
            if not hasattr(source, "fetch_index_search"):
                continue
            try:
                # Search for common index keywords to get available indices
                results = await source.fetch_index_search("指数", is_symbol=False)
                if results:
                    return results
            except Exception:
                continue
        return []

    @staticmethod
    def transform_data(
        query: AvailableIndicesQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceAvailableIndicesData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceAvailableIndicesData.model_validate(item) for item in data]
