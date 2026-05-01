"""ETF search with routed data sources."""

from __future__ import annotations

from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.etf_search import EtfSearchData, EtfSearchQueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.registry import build_default_registry


class FinanceEtfSearchData(EtfSearchData):
    """Finance ETF search data."""

    source: str | None = Field(default=None, description="Selected data source.")


class FinanceEtfSearchFetcher(Fetcher[EtfSearchQueryParams, list[FinanceEtfSearchData]]):
    """Fetcher for ETF search data."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> EtfSearchQueryParams:
        return EtfSearchQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: EtfSearchQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials
        registry = kwargs.get("registry") or build_default_registry()
        for source in registry.ordered_by_names(["eastmoney"]):
            if not hasattr(source, "fetch_etf_search"):
                continue
            try:
                results = await source.fetch_etf_search(query.query or "")
                if results:
                    return results
            except Exception:
                continue
        return []

    @staticmethod
    def transform_data(
        query: EtfSearchQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceEtfSearchData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceEtfSearchData.model_validate(item) for item in data]
