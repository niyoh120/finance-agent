"""World news aggregated from multiple sources."""

from __future__ import annotations

from datetime import date as dateType
from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.world_news import WorldNewsData, WorldNewsQueryParams
from openbb_core.provider.utils.errors import EmptyDataError

from openbb_finance.aggregator import aggregate_records
from openbb_finance.registry import build_default_registry


class FinanceWorldNewsFetcher(Fetcher[WorldNewsQueryParams, list[WorldNewsData]]):
    """Fetcher for priority-merged world news."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> WorldNewsQueryParams:
        return WorldNewsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: WorldNewsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials
        registry = kwargs.get("registry") or build_default_registry()
        sources = registry.ordered_by_names(["futunn", "openbb"])
        start_date = query.start_date
        end_date = query.end_date or dateType.today()

        async def fetch(source: Any) -> list[dict[str, Any]]:
            if hasattr(source, "fetch_world_news"):
                return await source.fetch_world_news(query.limit, start_date, end_date)
            return []

        return await aggregate_records(sources, fetch, key_fields=("date", "title"))

    @staticmethod
    def transform_data(
        query: WorldNewsQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[WorldNewsData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [
            WorldNewsData(
                date=row["date"],
                title=row.get("title", ""),
                author=row.get("author"),
                excerpt=row.get("excerpt"),
                body=row.get("body"),
                images=row.get("images"),
                url=row.get("url"),
            )
            for row in data
        ]
