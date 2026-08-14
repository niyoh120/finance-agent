"""Insider trading from ConvexValue /fmp/stable/insider-trading/search."""

from __future__ import annotations

from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.insider_trading import (
    InsiderTradingData,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.models._query_coerce import ConvexValueQueryParams
from openbb_finance.sources import convexvalue as cv


class FinanceInsiderTradingQueryParams(ConvexValueQueryParams):
    """Insider trading query.

    transaction_type and after are server-side filters (FMP supports them).
    Common transaction_type codes: P-Purchase, S-Sale, M-Exempt, F-InKind,
    J-Other, G-Gift. Use sort_by/sort_dir/limit at the CLI layer for ordering.
    """

    symbol: str = Field(description=QUERY_DESCRIPTIONS.get("symbol", ""))
    transaction_type: str | None = Field(
        default=None,
        description="FMP transaction code, e.g. P-Purchase, S-Sale.",
    )
    after: str | None = Field(
        default=None,
        description="Only trades after this date (YYYY-MM-DD). Server-side.",
    )
    limit: int | None = Field(default=None, ge=1)


class FinanceInsiderTradingData(InsiderTradingData):
    """Insider trade row (16 FMP fields, aligned via alias)."""

    __alias_dict__ = {
        "owner_cik": "reportingCik",
        "owner_name": "reportingName",
        "owner_title": "typeOfOwner",
        "ownership_type": "directOrIndirect",
        "security_type": "securityName",
        "transaction_price": "price",
        "acquisition_or_disposition": "acquisitionOrDisposition",
        "filing_url": "link",
        "company_cik": "cik",
    }

    form_type: str | None = Field(default=None)


class FinanceInsiderTradingFetcher(Fetcher[FinanceInsiderTradingQueryParams, list[FinanceInsiderTradingData]]):
    """Fetcher for ConvexValue/FMP insider trades."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceInsiderTradingQueryParams:
        return FinanceInsiderTradingQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceInsiderTradingQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials, kwargs
        return await cv.fetch_fmp(
            "insider-trading/search",
            symbol=query.symbol,
            transactionType=query.transaction_type,
            after=query.after,
            limit=query.limit if query.limit is not None else 50,
        )

    @staticmethod
    def transform_data(
        query: FinanceInsiderTradingQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceInsiderTradingData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceInsiderTradingData.model_validate(row) for row in data]
