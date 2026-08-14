"""Equity screener using TradingView data via tvscreener."""

from __future__ import annotations

import json
from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.equity_screener import (
    EquityScreenerData,
    EquityScreenerQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

ScreenerMarket = Literal["america", "hongkong", "china", "global"]


class FinanceEquityScreenerQueryParams(EquityScreenerQueryParams):
    """Finance equity screener query parameters.

    Supports two modes:
    1. Simple filters: Use individual parameters like price_min, volume_min, etc.
    2. Advanced filters: Use `filters` JSON string for arbitrary field filtering.

    Example filters JSON string:
        '{"PRICE": {"min": 50, "max": 200}, "VOLUME": {"min": 1000000}, "SECTOR": {"in": ["Technology"]}}'

    Example fields JSON string:
        '["NAME", "SYMBOL", "PRICE", "MACD_LEVEL_12_26"]'
    """

    market: ScreenerMarket | None = Field(default=None)
    limit: int = Field(default=150)

    # Simple filters (common use cases)
    price_min: float | None = Field(default=None)
    price_max: float | None = Field(default=None)
    change_percent_min: float | None = Field(default=None)
    change_percent_max: float | None = Field(default=None)
    volume_min: int | None = Field(default=None)
    volume_max: int | None = Field(default=None)
    market_cap_min: float | None = Field(default=None)
    market_cap_max: float | None = Field(default=None)
    rsi_min: float | None = Field(default=None)
    rsi_max: float | None = Field(default=None)
    sector: list[str] | str | None = Field(default=None)

    # Advanced filters: JSON string with arbitrary field conditions
    # Format: '{"FIELD_NAME": {"min": x, "max": y, "in": [...]}, ...}'
    filters: str | None = Field(
        default=None,
        description="Advanced filters as JSON string. Keys are StockField names, values are condition dicts.",
    )

    # Fields to return: JSON string
    # Format: '["FIELD1", "FIELD2", ...]'
    fields: str | None = Field(
        default=None,
        description="List of StockField names to return as JSON string.",
    )


class FinanceEquityScreenerData(EquityScreenerData):
    """Finance equity screener data.

    Returns dynamic fields based on the query.
    """

    model_config = {"extra": "allow"}

    name: str | None = Field(default=None)
    price: float | None = Field(default=None)
    change_percent: float | None = Field(default=None)
    volume: int | None = Field(default=None)
    market_cap: float | None = Field(default=None)
    sector: str | None = Field(default=None)
    rsi: float | None = Field(default=None)


class FinanceEquityScreenerFetcher(Fetcher[FinanceEquityScreenerQueryParams, list[FinanceEquityScreenerData]]):
    """Fetcher for equity screener data."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceEquityScreenerQueryParams:
        # Handle fields parameter - convert list to JSON string if needed
        if "fields" in params and isinstance(params["fields"], list):
            params["fields"] = json.dumps(params["fields"])
        return FinanceEquityScreenerQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceEquityScreenerQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials, kwargs
        from openbb_finance.sources.tradingview import fetch_equity_screener

        sector = query.sector.split(",") if isinstance(query.sector, str) else query.sector

        # Parse JSON strings
        filters_dict = None
        if query.filters:
            try:
                filters_dict = json.loads(query.filters)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid filters JSON: {exc.msg}") from exc
            if not isinstance(filters_dict, dict):
                raise ValueError("Invalid filters JSON: expected an object")

        fields_list = None
        if query.fields:
            try:
                fields_list = json.loads(query.fields)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid fields JSON: {exc.msg}") from exc
            if not isinstance(fields_list, list):
                raise ValueError("Invalid fields JSON: expected an array")

        return await fetch_equity_screener(
            market=query.market,
            limit=query.limit,
            price_min=query.price_min,
            price_max=query.price_max,
            change_percent_min=query.change_percent_min,
            change_percent_max=query.change_percent_max,
            volume_min=query.volume_min,
            volume_max=query.volume_max,
            market_cap_min=query.market_cap_min,
            market_cap_max=query.market_cap_max,
            rsi_min=query.rsi_min,
            rsi_max=query.rsi_max,
            sector=sector,
            filters=filters_dict,
            fields=fields_list,
        )

    @staticmethod
    def transform_data(
        query: FinanceEquityScreenerQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceEquityScreenerData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceEquityScreenerData.model_validate(item) for item in data]
