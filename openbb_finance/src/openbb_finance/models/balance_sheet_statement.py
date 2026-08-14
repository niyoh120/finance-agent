"""Balance sheet statement from ConvexValue /fmp/stable/balance-sheet-statement.

All 61 FMP fields retained; aliases map camelCase to snake_case.
"""

from __future__ import annotations

from datetime import date as dateType
from datetime import datetime
from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.balance_sheet import (
    BalanceSheetData,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.models._query_coerce import ConvexValueQueryParams
from openbb_finance.sources import convexvalue as cv

# FMP camelCase -> snake_case. Special cases (period_ending etc.) follow the
# openbb standard model field names; the rest are mechanical conversions.
_ALIAS: dict[str, str] = {
    "period_ending": "date",
    "fiscal_period": "period",
    "fiscal_year": "calendarYear",
    "filing_date": "fillingDate",
    "accepted_date": "acceptedDate",
    "reported_currency": "reportedCurrency",
}


class FinanceBalanceSheetQueryParams(ConvexValueQueryParams):
    """Balance sheet query."""

    symbol: str = Field(description=QUERY_DESCRIPTIONS.get("symbol", ""))
    period: Literal["annual", "quarter", "ttm"] = Field(default="annual")
    limit: int | None = Field(default=None, ge=1)


class FinanceBalanceSheetData(BalanceSheetData):
    """Balance sheet row (FMP field set, all retained)."""

    __alias_dict__ = _ALIAS

    filing_date: dateType | None = Field(default=None)
    accepted_date: datetime | None = Field(default=None)
    cik: str | None = Field(default=None)
    symbol: str | None = Field(default=None)
    reported_currency: str | None = Field(default=None)
    account_payables: int | None = Field(default=None)
    accounts_receivables: int | None = Field(default=None)
    accrued_expenses: int | None = Field(default=None)
    accumulated_other_comprehensive_income_loss: int | None = Field(default=None)
    additional_paid_in_capital: int | None = Field(default=None)
    capital_lease_obligations: int | None = Field(default=None)
    capital_lease_obligations_current: int | None = Field(default=None)
    capital_lease_obligations_non_current: int | None = Field(default=None)
    cash_and_cash_equivalents: int | None = Field(default=None)
    cash_and_short_term_investments: int | None = Field(default=None)
    common_stock: int | None = Field(default=None)
    deferred_revenue: int | None = Field(default=None)
    deferred_revenue_non_current: int | None = Field(default=None)
    deferred_tax_liabilities_non_current: int | None = Field(default=None)
    goodwill: int | None = Field(default=None)
    goodwill_and_intangible_assets: int | None = Field(default=None)
    intangible_assets: int | None = Field(default=None)
    inventory: int | None = Field(default=None)
    long_term_debt: int | None = Field(default=None)
    long_term_investments: int | None = Field(default=None)
    minority_interest: int | None = Field(default=None)
    net_debt: int | None = Field(default=None)
    net_receivables: int | None = Field(default=None)
    other_assets: int | None = Field(default=None)
    other_current_assets: int | None = Field(default=None)
    other_current_liabilities: int | None = Field(default=None)
    other_liabilities: int | None = Field(default=None)
    other_non_current_assets: int | None = Field(default=None)
    other_non_current_liabilities: int | None = Field(default=None)
    other_payables: int | None = Field(default=None)
    other_receivables: int | None = Field(default=None)
    other_total_stockholders_equity: int | None = Field(default=None)
    preferred_stock: int | None = Field(default=None)
    prepaids: int | None = Field(default=None)
    property_plant_equipment_net: int | None = Field(default=None)
    retained_earnings: int | None = Field(default=None)
    short_term_debt: int | None = Field(default=None)
    short_term_investments: int | None = Field(default=None)
    tax_assets: int | None = Field(default=None)
    tax_payables: int | None = Field(default=None)
    total_assets: int | None = Field(default=None)
    total_current_assets: int | None = Field(default=None)
    total_current_liabilities: int | None = Field(default=None)
    total_debt: int | None = Field(default=None)
    total_equity: int | None = Field(default=None)
    total_investments: int | None = Field(default=None)
    total_liabilities: int | None = Field(default=None)
    total_liabilities_and_total_equity: int | None = Field(default=None)
    total_non_current_assets: int | None = Field(default=None)
    total_non_current_liabilities: int | None = Field(default=None)
    total_payables: int | None = Field(default=None)
    total_stockholders_equity: int | None = Field(default=None)
    treasury_stock: int | None = Field(default=None)


class FinanceBalanceSheetFetcher(Fetcher[FinanceBalanceSheetQueryParams, list[FinanceBalanceSheetData]]):
    """Fetcher for ConvexValue/FMP balance sheets."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceBalanceSheetQueryParams:
        return FinanceBalanceSheetQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceBalanceSheetQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials, kwargs
        endpoint = "balance-sheet-statement-ttm" if query.period == "ttm" else "balance-sheet-statement"
        return await cv.fetch_fmp(
            endpoint,
            symbol=query.symbol,
            period=None if query.period == "ttm" else query.period,
            limit=query.limit if query.limit is not None else 5,
        )

    @staticmethod
    def transform_data(
        query: FinanceBalanceSheetQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceBalanceSheetData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceBalanceSheetData.model_validate(row) for row in data]
