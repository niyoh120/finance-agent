"""Analyst estimates from ConvexValue /fmp/stable/analyst-estimates."""

from __future__ import annotations

from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.analyst_estimates import (
    AnalystEstimatesData,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.models._query_coerce import ConvexValueQueryParams
from openbb_finance.sources import convexvalue as cv


class FinanceAnalystEstimatesQueryParams(ConvexValueQueryParams):
    """Analyst estimates query."""

    symbol: str = Field(description=QUERY_DESCRIPTIONS.get("symbol", ""))
    period: Literal["annual", "quarter"] = Field(default="annual")
    limit: int | None = Field(default=None, ge=1)


class FinanceAnalystEstimatesData(AnalystEstimatesData):
    """Analyst estimates row (22 FMP fields, all aligned via alias)."""

    __alias_dict__ = {
        "estimated_revenue_low": "revenueLow",
        "estimated_revenue_high": "revenueHigh",
        "estimated_revenue_avg": "revenueAvg",
        "estimated_sga_expense_low": "sgaExpenseLow",
        "estimated_sga_expense_high": "sgaExpenseHigh",
        "estimated_sga_expense_avg": "sgaExpenseAvg",
        "estimated_ebitda_low": "ebitdaLow",
        "estimated_ebitda_high": "ebitdaHigh",
        "estimated_ebitda_avg": "ebitdaAvg",
        "estimated_ebit_low": "ebitLow",
        "estimated_ebit_high": "ebitHigh",
        "estimated_ebit_avg": "ebitAvg",
        "estimated_net_income_low": "netIncomeLow",
        "estimated_net_income_high": "netIncomeHigh",
        "estimated_net_income_avg": "netIncomeAvg",
        "estimated_eps_low": "epsLow",
        "estimated_eps_high": "epsHigh",
        "estimated_eps_avg": "epsAvg",
        "number_analysts_estimated_revenue": "numAnalystsRevenue",
        "number_analysts_eps": "numAnalystsEps",
    }


class FinanceAnalystEstimatesFetcher(Fetcher[FinanceAnalystEstimatesQueryParams, list[FinanceAnalystEstimatesData]]):
    """Fetcher for ConvexValue/FMP analyst estimates."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceAnalystEstimatesQueryParams:
        return FinanceAnalystEstimatesQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceAnalystEstimatesQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials, kwargs
        return await cv.fetch_fmp(
            "analyst-estimates",
            symbol=query.symbol,
            period=query.period,
            limit=query.limit if query.limit is not None else 10,
        )

    @staticmethod
    def transform_data(
        query: FinanceAnalystEstimatesQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceAnalystEstimatesData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceAnalystEstimatesData.model_validate(row) for row in data]
