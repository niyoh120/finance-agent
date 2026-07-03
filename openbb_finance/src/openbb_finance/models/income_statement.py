"""Income statement from ConvexValue /fmp/stable/income-statement.

Inherits the standard openbb IncomeStatementData and mirrors the openbb-fmp
field layout: __alias_dict__ maps FMP camelCase -> openbb snake_case, and the
FMP-specific fields are redeclared as typed extensions. period defaults to
annual (CV/FMP supports annual, quarter, ttm).
"""

from __future__ import annotations

from datetime import date as dateType
from datetime import datetime
from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.income_statement import (
    IncomeStatementData,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.models._query_coerce import ConvexValueQueryParams
from openbb_finance.sources import convexvalue as cv


class FinanceIncomeStatementQueryParams(ConvexValueQueryParams):
    """Income statement query.

    Declared as a plain QueryParams (not inheriting IncomeStatementQueryParams)
    so all fields live in one class. The OpenBB API layer splits standard vs
    extra params and would inject Query() defaults for provider-specific
    fields like `period`; keeping everything in one class avoids that.
    """

    symbol: str = Field(description=QUERY_DESCRIPTIONS.get("symbol", ""))
    period: Literal["annual", "quarter", "ttm"] = Field(default="annual")
    limit: int | None = Field(default=None, ge=1)


class FinanceIncomeStatementData(IncomeStatementData):
    """Income statement row (FMP field set, all retained)."""

    __alias_dict__ = {
        "period_ending": "date",
        "fiscal_period": "period",
        "fiscal_year": "calendarYear",
        "filing_date": "fillingDate",
        "accepted_date": "acceptedDate",
        "reported_currency": "reportedCurrency",
        "revenue": "revenue",
        "cost_of_revenue": "costOfRevenue",
        "gross_profit": "grossProfit",
        "general_and_admin_expense": "generalAndAdministrativeExpenses",
        "research_and_development_expense": "researchAndDevelopmentExpenses",
        "selling_and_marketing_expense": "sellingAndMarketingExpenses",
        "selling_general_and_admin_expense": "sellingGeneralAndAdministrativeExpenses",
        "other_expenses": "otherExpenses",
        "total_operating_expenses": "operatingExpenses",
        "cost_and_expenses": "costAndExpenses",
        "interest_income": "interestIncome",
        "total_interest_expense": "interestExpense",
        "depreciation_and_amortization": "depreciationAndAmortization",
        "ebit": "ebit",
        "ebitda": "ebitda",
        "total_operating_income": "operatingIncome",
        "total_other_income_expenses": "totalOtherIncomeExpensesNet",
        "total_pre_tax_income": "incomeBeforeTax",
        "income_tax_expense": "incomeTaxExpense",
        "consolidated_net_income": "netIncome",
        "basic_earnings_per_share": "eps",
        "diluted_earnings_per_share": "epsDiluted",
        "weighted_average_basic_shares_outstanding": "weightedAverageShsOut",
        "weighted_average_diluted_shares_outstanding": "weightedAverageShsOutDil",
    }

    filing_date: dateType | None = Field(default=None)
    accepted_date: datetime | None = Field(default=None)
    cik: str | None = Field(default=None)
    symbol: str | None = Field(default=None)
    reported_currency: str | None = Field(default=None)
    revenue: int | None = Field(default=None)
    cost_of_revenue: int | None = Field(default=None)
    gross_profit: int | None = Field(default=None)
    general_and_admin_expense: int | None = Field(default=None)
    research_and_development_expense: int | None = Field(default=None)
    selling_and_marketing_expense: int | None = Field(default=None)
    selling_general_and_admin_expense: int | None = Field(default=None)
    other_expenses: int | None = Field(default=None)
    total_operating_expenses: int | None = Field(default=None)
    cost_and_expenses: int | None = Field(default=None)
    interest_income: int | None = Field(default=None)
    total_interest_expense: int | None = Field(default=None)
    net_interest_income: int | None = Field(default=None)
    depreciation_and_amortization: int | None = Field(default=None)
    ebit: int | None = Field(default=None)
    ebitda: int | None = Field(default=None)
    total_operating_income: int | None = Field(default=None)
    non_operating_income_excluding_interest: int | None = Field(default=None)
    net_income_from_continuing_operations: int | None = Field(default=None)
    net_income_from_discontinued_operations: int | None = Field(default=None)
    total_other_income_expenses: int | None = Field(default=None)
    total_pre_tax_income: int | None = Field(default=None)
    income_tax_expense: int | None = Field(default=None)
    other_adjustments_to_net_income: int | None = Field(default=None)
    net_income_deductions: int | None = Field(default=None)
    consolidated_net_income: int | None = Field(default=None)
    bottom_line_net_income: int | None = Field(default=None)
    basic_earnings_per_share: float | None = Field(default=None)
    diluted_earnings_per_share: float | None = Field(default=None)
    weighted_average_basic_shares_outstanding: int | None = Field(default=None)
    weighted_average_diluted_shares_outstanding: int | None = Field(default=None)


class FinanceIncomeStatementFetcher(
    Fetcher[FinanceIncomeStatementQueryParams, list[FinanceIncomeStatementData]]
):
    """Fetcher for ConvexValue/FMP income statements."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceIncomeStatementQueryParams:
        return FinanceIncomeStatementQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceIncomeStatementQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials, kwargs
        endpoint = "income-statement-ttm" if query.period == "ttm" else "income-statement"
        return await cv.fetch_fmp(
            endpoint,
            symbol=query.symbol,
            period=None if query.period == "ttm" else query.period,
            limit=query.limit if query.limit is not None else 5,
        )

    @staticmethod
    def transform_data(
        query: FinanceIncomeStatementQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceIncomeStatementData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceIncomeStatementData.model_validate(row) for row in data]
