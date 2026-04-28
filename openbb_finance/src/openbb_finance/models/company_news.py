"""Company news aggregated from multiple sources."""

from __future__ import annotations

from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.company_news import CompanyNewsData, CompanyNewsQueryParams
from openbb_core.provider.utils.errors import EmptyDataError

from openbb_finance.aggregator import aggregate_records
from openbb_finance.registry import build_default_registry
from openbb_finance.sources.base import infer_market


class FinanceCompanyNewsFetcher(Fetcher[CompanyNewsQueryParams, list[CompanyNewsData]]):
    """Fetcher for priority-merged company news."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> CompanyNewsQueryParams:
        return CompanyNewsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: CompanyNewsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials
        registry = kwargs.get("registry") or build_default_registry()
        market = infer_market(query.symbol) if query.symbol else "global"
        names = ["futunn", "openbb"] if market in {"us", "hk"} else ["futunn", "akshare", "openbb"]
        sources = registry.ordered_by_names(names)

        async def fetch(source: Any) -> list[dict[str, Any]]:
            if hasattr(source, "fetch_news"):
                return await source.fetch_news(query.symbol, query.limit)
            return []

        return await aggregate_records(sources, fetch, key_fields=("date", "title"))

    @staticmethod
    def transform_data(
        query: CompanyNewsQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[CompanyNewsData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [
            CompanyNewsData(
                date=row["date"],
                title=row.get("title", ""),
                author=row.get("author"),
                excerpt=row.get("excerpt"),
                body=row.get("body"),
                url=row.get("url"),
                symbols=row.get("symbols"),
            )
            for row in data
        ]
