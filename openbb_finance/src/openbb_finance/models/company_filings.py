"""SEC 8-K filings from ConvexValue /fmp/stable/sec-filings-8k."""

from __future__ import annotations

from datetime import date as dateType
from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.company_filings import (
    CompanyFilingsData,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.models._query_coerce import ConvexValueQueryParams
from openbb_finance.sources import convexvalue as cv


class FinanceCompanyFilingsQueryParams(ConvexValueQueryParams):
    """SEC 8-K filings query.

    from/to (YYYY-MM-DD) and page are server-side filters supported by FMP.
    """

    symbol: str | None = Field(default=None, description=QUERY_DESCRIPTIONS.get("symbol", ""))
    from_date: str | None = Field(default=None, description="Start date (YYYY-MM-DD). Server-side.")
    to_date: str | None = Field(default=None, description="End date (YYYY-MM-DD). Server-side.")
    page: int | None = Field(default=None)
    limit: int | None = Field(default=None, ge=1)


class FinanceCompanyFilingsData(CompanyFilingsData):
    """SEC 8-K filing row."""

    __alias_dict__ = {
        "filing_date": "filingDate",
        "report_type": "formType",
        "report_url": "finalLink",
    }

    accepted_date: dateType | None = Field(default=None)
    cik: str | None = Field(default=None)
    has_financials: bool | None = Field(default=None)
    link: str | None = Field(default=None, description="Standard filing URL.")


class FinanceCompanyFilingsFetcher(Fetcher[FinanceCompanyFilingsQueryParams, list[FinanceCompanyFilingsData]]):
    """Fetcher for ConvexValue/FMP SEC 8-K filings."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceCompanyFilingsQueryParams:
        return FinanceCompanyFilingsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceCompanyFilingsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials, kwargs
        return await cv.fetch_fmp(
            "sec-filings-8k",
            symbol=query.symbol,
            **{"from": query.from_date, "to": query.to_date},
            page=query.page,
            limit=query.limit if query.limit is not None else 50,
        )

    @staticmethod
    def transform_data(
        query: FinanceCompanyFilingsQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceCompanyFilingsData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceCompanyFilingsData.model_validate(row) for row in data]
