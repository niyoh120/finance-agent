"""Index snapshots with routed data sources."""

from __future__ import annotations

from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.index_snapshots import (
    IndexSnapshotsData,
    IndexSnapshotsQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.registry import build_default_registry


class FinanceIndexSnapshotsData(IndexSnapshotsData):
    """Finance index snapshots data."""

    source: str | None = Field(default=None, description="Selected data source.")


class FinanceIndexSnapshotsQueryParams(IndexSnapshotsQueryParams):
    """Finance index snapshots query parameters."""

    symbol: list[str] | None = Field(
        default=None,
        description="List of index symbols to fetch. If None, returns default indices for the region.",
    )


class FinanceIndexSnapshotsFetcher(Fetcher[FinanceIndexSnapshotsQueryParams, list[FinanceIndexSnapshotsData]]):
    """Fetcher for index snapshots data."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceIndexSnapshotsQueryParams:
        return FinanceIndexSnapshotsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceIndexSnapshotsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials
        registry = kwargs.get("registry") or build_default_registry()
        region = query.region or "cn"

        for source in registry.ordered_by_names(["tickflow"]):
            if not hasattr(source, "fetch_index_snapshots"):
                continue
            try:
                results = await source.fetch_index_snapshots(
                    region=region,
                    symbols=query.symbol,
                )
                if results:
                    return results
            except Exception:
                continue
        return []

    @staticmethod
    def transform_data(
        query: FinanceIndexSnapshotsQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceIndexSnapshotsData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceIndexSnapshotsData.model_validate(item) for item in data]
