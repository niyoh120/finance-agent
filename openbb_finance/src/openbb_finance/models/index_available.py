"""Index available with routed data sources."""

from __future__ import annotations

from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.available_indices import (
    AvailableIndicesData,
    AvailableIndicesQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.registry import build_default_registry
from openbb_finance.sources.tickflow import static_available_indices


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
        for source in registry.ordered_by_names(["tickflow"]):
            if not hasattr(source, "fetch_available_indices"):
                continue
            try:
                results = await source.fetch_available_indices()
                if results:
                    return _merge_available_indices(results, static_available_indices())
            except Exception:
                continue
        return static_available_indices()

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


def _merge_available_indices(
    primary: list[dict[str, Any]],
    fallback: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged = list(primary)
    seen = {str(item.get("symbol", "")).upper() for item in primary}
    for item in fallback:
        symbol = str(item.get("symbol", "")).upper()
        if symbol and symbol not in seen:
            merged.append(item)
            seen.add(symbol)
    return merged
