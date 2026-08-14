"""Senate (government) trades from ConvexValue /fmp/stable/senate-trades.

openbb's GovernmentTradesData is generic across chambers; we fix chamber to
'senate' because CV/FMP exposes that endpoint reliably. House/senate-trades
RSS endpoints exist but were unstable during probe (502), so we restrict to
senate-trades.
"""

from __future__ import annotations

from datetime import date as dateType
from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.government_trades import (
    GovernmentTradesData,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.models._query_coerce import ConvexValueQueryParams
from openbb_finance.sources import convexvalue as cv


class FinanceGovernmentTradesQueryParams(ConvexValueQueryParams):
    """Senate trades query.

    The CV/FMP senate-trades endpoint supports page-based pagination.
    from/to/after are NOT supported server-side (verified during probe).
    """

    symbol: str | None = Field(default=None, description=QUERY_DESCRIPTIONS.get("symbol", ""))
    chamber: Literal["senate"] = Field(default="senate")
    page: int | None = Field(default=None, ge=0, description="0-indexed page number.")
    limit: int | None = Field(default=None, ge=1)


class FinanceGovernmentTradesData(GovernmentTradesData):
    """Senate trade row (16 FMP fields retained as extensions)."""

    # GovernmentTradesData.date is required and validated via a camelCase
    # alias_generator; the FMP senate endpoint exposes transactionDate only,
    # so we copy it in transform_data rather than rely on __alias_dict__
    # (which loses to the generator-derived alias).

    first_name: str | None = Field(default=None)
    office: str | None = Field(default=None)
    district: str | None = Field(default=None)
    owner: str | None = Field(default=None)
    asset_description: str | None = Field(default=None)
    asset_type: str | None = Field(default=None)
    transaction_type: str | None = Field(default=None)
    amount: str | None = Field(default=None, description="Disclosed amount range.")
    capital_gains_over_200_usd: bool | None = Field(default=None)
    disclosure_date: dateType | None = Field(default=None)
    link: str | None = Field(default=None, description="Source disclosure URL.")
    senate_id: str | None = Field(default=None)
    comment: str | None = Field(default=None)


class FinanceGovernmentTradesFetcher(Fetcher[FinanceGovernmentTradesQueryParams, list[FinanceGovernmentTradesData]]):
    """Fetcher for ConvexValue/FMP senate trades."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceGovernmentTradesQueryParams:
        return FinanceGovernmentTradesQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceGovernmentTradesQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials, kwargs
        return await cv.fetch_fmp(
            "senate-trades",
            symbol=query.symbol,
            page=query.page,
            limit=query.limit if query.limit is not None else 100,
        )

    @staticmethod
    def transform_data(
        query: FinanceGovernmentTradesQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceGovernmentTradesData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        for row in data:
            # Map FMP fields to the names the standard model validates against.
            if row.get("date") is None and row.get("transactionDate"):
                row["date"] = row["transactionDate"]
            if row.get("representative") is None:
                row["representative"] = row.get("lastName")
            # senate-trades uses the short key `type` for the action; the
            # standard GovernmentTradesData field is transaction_type, whose
            # auto camelCase alias (transactionType) does not match.
            if row.get("transaction_type") is None:
                row["transaction_type"] = row.get("type")
            # capitalGainsOver200USD has an acronym that the auto camelCase
            # alias generator would render as capitalGainsOver200Usd.
            if row.get("capital_gains_over_200_usd") is None:
                row["capital_gains_over_200_usd"] = row.get("capitalGainsOver200USD")
        return [FinanceGovernmentTradesData.model_validate(row) for row in data]
