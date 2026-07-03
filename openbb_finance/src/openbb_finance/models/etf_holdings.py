"""ETF holdings from ConvexValue /fmp/stable/etf/holdings."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.etf_holdings import (
    EtfHoldingsData,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.models._query_coerce import ConvexValueQueryParams
from openbb_finance.sources import convexvalue as cv


class FinanceEtfHoldingsQueryParams(ConvexValueQueryParams):
    """ETF holdings query."""

    symbol: str = Field(description=QUERY_DESCRIPTIONS.get("symbol", ""))
    limit: int | None = Field(default=None, ge=1)


class FinanceEtfHoldingsData(EtfHoldingsData):
    """ETF holding row (9 FMP fields retained as extensions)."""

    isin: str | None = Field(default=None, description="International securities ID.")
    cusip: str | None = Field(default=None, description="CUSIP identifier.")
    shares_number: float | None = Field(default=None)
    market_value: float | None = Field(default=None)
    weight_percentage: float | None = Field(
        default=None, description="Weight as a percentage (e.g. 6.21 for 6.21%)."
    )
    updated_at: datetime | None = Field(default=None)
    asset: str | None = Field(default=None, description="Underlying asset ticker.")

    __alias_dict__ = {
        "cusip": "securityCusip",
    }


class FinanceEtfHoldingsFetcher(
    Fetcher[FinanceEtfHoldingsQueryParams, list[FinanceEtfHoldingsData]]
):
    """Fetcher for ConvexValue/FMP ETF holdings."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceEtfHoldingsQueryParams:
        return FinanceEtfHoldingsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceEtfHoldingsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials, kwargs
        return await cv.fetch_fmp(
            "etf/holdings",
            symbol=query.symbol,
            limit=query.limit,
        )

    @staticmethod
    def transform_data(
        query: FinanceEtfHoldingsQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceEtfHoldingsData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceEtfHoldingsData.model_validate(row) for row in data]
