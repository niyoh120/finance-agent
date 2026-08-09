"""Futures quotes via the tdx primary source.

openbb has no FuturesQuote standard model, so we define a custom QueryParams /
Data pair following the FinanceOptionsScreenerFetcher precedent. The dynamic
API layer generates an empty StandardParams plus a full-field ExtraParams for
such models, and the CLI drives them through _execute_provider_model directly.
"""

from __future__ import annotations

from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.registry import build_default_registry


class FinanceFuturesQuoteQueryParams(QueryParams):
    """Futures quote query."""

    symbol: str = Field(
        description="Futures symbol, e.g. rb.SHFE, GC.COMEX, AU.SGE. No expiration = main continuous."
    )
    expiration: str | None = Field(
        default=None,
        description="Contract expiration in YYYY-MM form; None for the main continuous contract.",
    )


class FinanceFuturesQuoteData(Data):
    """Futures quote data."""

    symbol: str | None = Field(default=None, description="Requested symbol.")
    name: str | None = Field(default=None, description="Product or contract name.")
    last_price: float | None = Field(default=None, description="Latest traded price.")
    open: float | None = Field(default=None)
    high: float | None = Field(default=None)
    low: float | None = Field(default=None)
    prev_close: float | None = Field(default=None)
    volume: float | None = Field(default=None)
    change: float | None = Field(default=None, description="Change vs previous close.")
    change_percent: float | None = Field(default=None, description="Change percent vs previous close.")
    source: str | None = Field(default=None, description="Selected data source.")


class FinanceFuturesQuoteFetcher(Fetcher[FinanceFuturesQuoteQueryParams, list[FinanceFuturesQuoteData]]):
    """Fetcher for futures quote data (tdx goods_quotes covers every ExMarket)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceFuturesQuoteQueryParams:
        return FinanceFuturesQuoteQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceFuturesQuoteQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials
        registry = kwargs.get("registry") or build_default_registry()
        for source in registry.ordered_by_names(["tdx"]):
            if not hasattr(source, "fetch_quote"):
                continue
            try:
                return [await source.fetch_quote(query.symbol, query.expiration)]
            except Exception:
                continue
        return []

    @staticmethod
    def transform_data(
        query: FinanceFuturesQuoteQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceFuturesQuoteData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceFuturesQuoteData.model_validate(item) for item in data]
