"""Equity quotes with routed data sources."""

from __future__ import annotations

from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.equity_quote import EquityQuoteData, EquityQuoteQueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.registry import build_default_registry
from openbb_finance.sources.base import infer_market

# Fields that identify a quote but carry no market data. A record holding only
# these is an empty upstream snapshot (observed on tdx: row exists, every price
# field null); after CLI null-stripping it degrades to {"symbol", "source"} and
# reads as "no data", so the router treats it as a source failure and falls
# through to the next source.
_QUOTE_IDENTIFIER_FIELDS = frozenset({"symbol", "name", "source", "exchange", "type", "expiration", "currency"})


def _quote_has_market_data(record: dict[str, Any]) -> bool:
    """True when the quote carries at least one non-identifier, non-null value."""
    return any(key not in _QUOTE_IDENTIFIER_FIELDS and value is not None for key, value in record.items())


class FinanceEquityQuoteData(EquityQuoteData):
    """Finance equity quote data."""

    source: str | None = Field(default=None, description="Selected data source.")


class FinanceEquityQuoteFetcher(Fetcher[EquityQuoteQueryParams, list[FinanceEquityQuoteData]]):
    """Fetcher for routed equity quote data."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> EquityQuoteQueryParams:
        return EquityQuoteQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: EquityQuoteQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials
        registry = kwargs.get("registry") or build_default_registry()
        market = infer_market(query.symbol)
        if market == "cn":
            names = ["tdx", "tickflow", "akshare"]
        elif market == "us":
            names = ["schwab", "tdx", "tickflow"]
        else:
            # hk/global/future: schwab only covers US symbols; keep the
            # original order and skip a guaranteed-to-fail local request.
            names = ["tdx", "tickflow"]
        for source in registry.ordered_by_names(names):
            if not hasattr(source, "fetch_quote"):
                continue
            try:
                records = [await source.fetch_quote(query.symbol)]
            except Exception:
                continue
            # Identifier-only record (upstream empty snapshot) counts as a source
            # failure: keep falling through instead of short-circuiting the chain.
            if _quote_has_market_data(records[0]):
                return records
        return []

    @staticmethod
    def transform_data(
        query: EquityQuoteQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceEquityQuoteData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceEquityQuoteData.model_validate(item) for item in data]
