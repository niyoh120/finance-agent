"""GDP nominal data with multi-source aggregation."""

from __future__ import annotations

from contextvars import ContextVar
from datetime import date as dateType
from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.gdp_nominal import (
    GdpNominalData,
    GdpNominalQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.registry import build_default_registry

_GDP_NOMINAL_COUNTRY_CONTEXT: ContextVar[str | None] = ContextVar(
    "finance_gdp_nominal_country",
    default=None,
)


def set_gdp_nominal_country_context(country: str | None):
    return _GDP_NOMINAL_COUNTRY_CONTEXT.set(country)


def reset_gdp_nominal_country_context(token: Any) -> None:
    _GDP_NOMINAL_COUNTRY_CONTEXT.reset(token)


class FinanceGdpNominalQueryParams(GdpNominalQueryParams):
    """Finance GDP nominal query."""

    country: str | None = Field(default="china", description="The country to get data.")


class FinanceGdpNominalData(GdpNominalData):
    """Finance GDP nominal data."""

    pass


class FinanceGdpNominalFetcher(
    Fetcher[FinanceGdpNominalQueryParams, list[FinanceGdpNominalData]]
):
    """Fetcher for GDP nominal data with multi-source support."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceGdpNominalQueryParams:
        country = _GDP_NOMINAL_COUNTRY_CONTEXT.get()
        if country is not None and "country" not in params:
            params = {**params, "country": country}
        return FinanceGdpNominalQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceGdpNominalQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials
        registry = kwargs.get("registry") or build_default_registry()
        
        # Determine if this is a China data request
        country = (query.country or "").lower()
        is_china = country in {"china", "cn", "中国", "chinese"}
        
        if is_china:
            # Use AKShare for China data
            akshare_source = registry.get("akshare")
            if akshare_source and hasattr(akshare_source, "fetch_macro_gdp"):
                data = await akshare_source.fetch_macro_gdp()
                # Transform to match GDP nominal format
                rows = [
                    {
                        "date": row["date"],
                        "country": "china",
                        "value": row.get("value"),
                        "source": "akshare",
                    }
                    for row in data
                ]
                return _filter_date_range(rows, query.start_date, query.end_date)
            return []
        
        # For non-China data, try to use OpenBB built-in providers
        try:
            if "openbb_client" in kwargs:
                openbb_client = kwargs["openbb_client"]
            else:
                from openbb import obb as openbb_client

            result = openbb_client.economy.gdp.nominal(
                start_date=query.start_date,
                end_date=query.end_date,
                country=query.country,
                provider="oecd",  # Use OECD as default provider for international data
            )
            if result and hasattr(result, 'results'):
                return [
                    {
                        "date": item.date,
                        "country": item.country,
                        "value": item.value,
                    }
                    for item in result.results
                ]
        except Exception:
            pass
        
        return []

    @staticmethod
    def transform_data(
        query: FinanceGdpNominalQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceGdpNominalData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [
            FinanceGdpNominalData(
                date=_to_date(row["date"]),
                country=row.get("country"),
                value=row.get("value"),
            )
            for row in data
        ]


def _to_date(value: Any) -> dateType:
    if isinstance(value, dateType):
        return value
    if isinstance(value, str):
        try:
            return dateType.fromisoformat(value[:10])
        except ValueError:
            if len(value) == 7:  # YYYY-MM
                return dateType.fromisoformat(value + "-01")
            elif len(value) == 8:  # YYYYMMDD
                return dateType.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:8]}")
    return dateType.today()


def _filter_date_range(
    data: list[dict[str, Any]],
    start_date: dateType | None,
    end_date: dateType | None,
) -> list[dict[str, Any]]:
    if not start_date and not end_date:
        return data
    return [
        row
        for row in data
        if (not start_date or _to_date(row["date"]) >= start_date)
        and (not end_date or _to_date(row["date"]) <= end_date)
    ]
