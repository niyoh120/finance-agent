"""Financial ratios from ConvexValue /fmp/stable/ratios.

All ~64 FMP ratio fields retained (camelCase -> snake_case).
"""

from __future__ import annotations

from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.financial_ratios import (
    FinancialRatiosData,
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
    "reported_currency": "reportedCurrency",
    # Acronym that the auto camelCase generator would render as netIncomePerEbt.
    "net_income_per_ebt": "netIncomePerEBT",
}


class FinanceFinancialRatiosQueryParams(ConvexValueQueryParams):
    """Financial ratios query."""

    symbol: str = Field(description=QUERY_DESCRIPTIONS.get("symbol", ""))
    period: Literal["annual", "quarter"] = Field(default="annual")
    limit: int | None = Field(default=None, ge=1)


class FinanceFinancialRatiosData(FinancialRatiosData):
    """Financial ratios row (FMP field set, all retained)."""

    __alias_dict__ = _ALIAS

    symbol: str | None = Field(default=None)
    reported_currency: str | None = Field(default=None)
    asset_turnover: float | None = Field(default=None)
    book_value_per_share: float | None = Field(default=None)
    bottom_line_profit_margin: float | None = Field(default=None)
    capex_per_share: float | None = Field(default=None)
    capital_expenditure_coverage_ratio: float | None = Field(default=None)
    cash_per_share: float | None = Field(default=None)
    cash_ratio: float | None = Field(default=None)
    continuous_operations_profit_margin: float | None = Field(default=None)
    current_ratio: float | None = Field(default=None)
    debt_service_coverage_ratio: float | None = Field(default=None)
    debt_to_assets_ratio: float | None = Field(default=None)
    debt_to_capital_ratio: float | None = Field(default=None)
    debt_to_equity_ratio: float | None = Field(default=None)
    debt_to_market_cap: float | None = Field(default=None)
    dividend_paid_and_capex_coverage_ratio: float | None = Field(default=None)
    dividend_payout_ratio: float | None = Field(default=None)
    dividend_per_share: float | None = Field(default=None)
    dividend_yield: float | None = Field(default=None)
    dividend_yield_percentage: float | None = Field(default=None)
    ebit_margin: float | None = Field(default=None)
    ebitda_margin: float | None = Field(default=None)
    ebt_per_ebit: float | None = Field(default=None)
    effective_tax_rate: float | None = Field(default=None)
    enterprise_value_multiple: float | None = Field(default=None)
    financial_leverage_ratio: float | None = Field(default=None)
    fixed_asset_turnover: float | None = Field(default=None)
    forward_price_to_earnings_growth_ratio: float | None = Field(default=None)
    free_cash_flow_operating_cash_flow_ratio: float | None = Field(default=None)
    free_cash_flow_per_share: float | None = Field(default=None)
    gross_profit_margin: float | None = Field(default=None)
    interest_coverage_ratio: float | None = Field(default=None)
    interest_debt_per_share: float | None = Field(default=None)
    inventory_turnover: float | None = Field(default=None)
    long_term_debt_to_capital_ratio: float | None = Field(default=None)
    net_income_per_ebt: float | None = Field(default=None)
    net_income_per_share: float | None = Field(default=None)
    net_profit_margin: float | None = Field(default=None)
    operating_cash_flow_coverage_ratio: float | None = Field(default=None)
    operating_cash_flow_per_share: float | None = Field(default=None)
    operating_cash_flow_ratio: float | None = Field(default=None)
    operating_cash_flow_sales_ratio: float | None = Field(default=None)
    operating_profit_margin: float | None = Field(default=None)
    payables_turnover: float | None = Field(default=None)
    pretax_profit_margin: float | None = Field(default=None)
    price_to_book_ratio: float | None = Field(default=None)
    price_to_earnings_growth_ratio: float | None = Field(default=None)
    price_to_earnings_ratio: float | None = Field(default=None)
    price_to_fair_value: float | None = Field(default=None)
    price_to_free_cash_flow_ratio: float | None = Field(default=None)
    price_to_operating_cash_flow_ratio: float | None = Field(default=None)
    price_to_sales_ratio: float | None = Field(default=None)
    quick_ratio: float | None = Field(default=None)
    receivables_turnover: float | None = Field(default=None)
    revenue_per_share: float | None = Field(default=None)
    shareholders_equity_per_share: float | None = Field(default=None)
    short_term_operating_cash_flow_coverage_ratio: float | None = Field(default=None)
    solvency_ratio: float | None = Field(default=None)
    tangible_book_value_per_share: float | None = Field(default=None)
    working_capital_turnover_ratio: float | None = Field(default=None)


class FinanceFinancialRatiosFetcher(Fetcher[FinanceFinancialRatiosQueryParams, list[FinanceFinancialRatiosData]]):
    """Fetcher for ConvexValue/FMP financial ratios."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceFinancialRatiosQueryParams:
        return FinanceFinancialRatiosQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceFinancialRatiosQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials, kwargs
        # ratios-ttm exists but uses field names with a TTM suffix
        # (currentRatioTTM, etc.) that do not map to this model; TTM support
        # would need a separate Data class, so period is restricted to
        # annual/quarter here.
        return await cv.fetch_fmp(
            "ratios",
            symbol=query.symbol,
            period=query.period,
            limit=query.limit if query.limit is not None else 5,
        )

    @staticmethod
    def transform_data(
        query: FinanceFinancialRatiosQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceFinancialRatiosData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceFinancialRatiosData.model_validate(row) for row in data]
