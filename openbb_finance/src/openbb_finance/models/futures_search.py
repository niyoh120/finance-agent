"""Futures search with routed data sources (tdx goods_list primary, akshare fallback)."""

from __future__ import annotations

from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.futures_instruments import (
    FuturesInstrumentsData,
    FuturesInstrumentsQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.registry import build_default_registry


class FinanceFuturesSearchQueryParams(FuturesInstrumentsQueryParams):
    """Finance futures search query."""

    query: str = Field(
        description=("Search query: variety code (si), user symbol (si.GFEX), or Chinese product name (工业硅).")
    )
    is_symbol: bool = Field(
        default=False,
        description="Treat the query as a symbol fragment instead of a Chinese product name.",
    )


class FinanceFuturesSearchData(FuturesInstrumentsData):
    """Finance futures search result."""

    symbol: str | None = Field(
        default=None,
        description="User-facing futures symbol, e.g. SI.GFEX. Use with --expiration for month contracts.",
    )
    expiration: str | None = Field(
        default=None, description="Contract expiration in YYYY-MM form; None for the main continuous contract."
    )
    code: str | None = Field(default=None, description="Source-native contract code.")
    name: str | None = Field(default=None, description="Product or contract name.")
    exchange: str | None = Field(
        default=None, description="Exchange short code, e.g. SHFE, DCE, CZCE, CFFEX, GFEX, COMEX, NYMEX, CBOT, SGE."
    )
    source: str | None = Field(default=None, description="Selected data source.")


class FinanceFuturesSearchFetcher(Fetcher[FinanceFuturesSearchQueryParams, list[FinanceFuturesSearchData]]):
    """Fetcher for futures search data."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceFuturesSearchQueryParams:
        return FinanceFuturesSearchQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceFuturesSearchQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials
        registry = kwargs.get("registry") or build_default_registry()
        for source in registry.ordered_by_names(["tdx", "akshare"]):
            if not hasattr(source, "fetch_futures_search"):
                continue
            try:
                results = await source.fetch_futures_search(query.query, query.is_symbol)
                if results:
                    return results
            except Exception:
                continue
        return []

    @staticmethod
    def transform_data(
        query: FinanceFuturesSearchQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceFuturesSearchData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceFuturesSearchData.model_validate(item) for item in data]
