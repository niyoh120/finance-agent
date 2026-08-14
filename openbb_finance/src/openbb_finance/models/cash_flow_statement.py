"""Cash flow statement from ConvexValue /fmp/stable/cash-flow-statement.

All 47 FMP fields retained; aliases map camelCase to snake_case.
"""

from __future__ import annotations

from datetime import date as dateType
from datetime import datetime
from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.cash_flow import (
    CashFlowStatementData,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.models._query_coerce import ConvexValueQueryParams
from openbb_finance.sources import convexvalue as cv

_ALIAS: dict[str, str] = {
    "period_ending": "date",
    "fiscal_period": "period",
    "fiscal_year": "calendarYear",
    "filing_date": "fillingDate",
    "accepted_date": "acceptedDate",
    "reported_currency": "reportedCurrency",
}


class FinanceCashFlowQueryParams(ConvexValueQueryParams):
    """Cash flow statement query."""

    symbol: str = Field(description=QUERY_DESCRIPTIONS.get("symbol", ""))
    period: Literal["annual", "quarter", "ttm"] = Field(default="annual")
    limit: int | None = Field(default=None, ge=1)


class FinanceCashFlowData(CashFlowStatementData):
    """Cash flow statement row (FMP field set, all retained)."""

    __alias_dict__ = _ALIAS

    filing_date: dateType | None = Field(default=None)
    accepted_date: datetime | None = Field(default=None)
    cik: str | None = Field(default=None)
    symbol: str | None = Field(default=None)
    reported_currency: str | None = Field(default=None)
    accounts_payables: int | None = Field(default=None)
    accounts_receivables: int | None = Field(default=None)
    acquisitions_net: int | None = Field(default=None)
    capital_expenditure: int | None = Field(default=None)
    cash_at_beginning_of_period: int | None = Field(default=None)
    cash_at_end_of_period: int | None = Field(default=None)
    change_in_working_capital: int | None = Field(default=None)
    common_dividends_paid: int | None = Field(default=None)
    common_stock_issuance: int | None = Field(default=None)
    common_stock_repurchased: int | None = Field(default=None)
    deferred_income_tax: int | None = Field(default=None)
    depreciation_and_amortization: int | None = Field(default=None)
    effect_of_forex_changes_on_cash: int | None = Field(default=None)
    free_cash_flow: int | None = Field(default=None)
    income_taxes_paid: int | None = Field(default=None)
    interest_paid: int | None = Field(default=None)
    inventory: int | None = Field(default=None)
    investments_in_property_plant_and_equipment: int | None = Field(default=None)
    long_term_net_debt_issuance: int | None = Field(default=None)
    net_cash_provided_by_financing_activities: int | None = Field(default=None)
    net_cash_provided_by_investing_activities: int | None = Field(default=None)
    net_cash_provided_by_operating_activities: int | None = Field(default=None)
    net_change_in_cash: int | None = Field(default=None)
    net_common_stock_issuance: int | None = Field(default=None)
    net_debt_issuance: int | None = Field(default=None)
    net_dividends_paid: int | None = Field(default=None)
    net_income: int | None = Field(default=None)
    net_preferred_stock_issuance: int | None = Field(default=None)
    net_stock_issuance: int | None = Field(default=None)
    operating_cash_flow: int | None = Field(default=None)
    other_financing_activities: int | None = Field(default=None)
    other_investing_activities: int | None = Field(default=None)
    other_non_cash_items: int | None = Field(default=None)
    other_working_capital: int | None = Field(default=None)
    preferred_dividends_paid: int | None = Field(default=None)
    purchases_of_investments: int | None = Field(default=None)
    sales_maturities_of_investments: int | None = Field(default=None)
    short_term_net_debt_issuance: int | None = Field(default=None)
    stock_based_compensation: int | None = Field(default=None)


class FinanceCashFlowFetcher(Fetcher[FinanceCashFlowQueryParams, list[FinanceCashFlowData]]):
    """Fetcher for ConvexValue/FMP cash flow statements."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceCashFlowQueryParams:
        return FinanceCashFlowQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceCashFlowQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials, kwargs
        # FMP exposes TTM via a dedicated endpoint; routing period=ttm to the
        # regular endpoint returns the latest annual report, not real TTM.
        endpoint = "cash-flow-statement-ttm" if query.period == "ttm" else "cash-flow-statement"
        return await cv.fetch_fmp(
            endpoint,
            symbol=query.symbol,
            period=None if query.period == "ttm" else query.period,
            limit=query.limit if query.limit is not None else 5,
        )

    @staticmethod
    def transform_data(
        query: FinanceCashFlowQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceCashFlowData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceCashFlowData.model_validate(row) for row in data]
