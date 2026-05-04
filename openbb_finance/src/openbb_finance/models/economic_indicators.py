"""Economic indicators with multi-source aggregation."""

from __future__ import annotations

from datetime import date as dateType
from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.economic_indicators import (
    EconomicIndicatorsData,
    EconomicIndicatorsQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError

from openbb_finance.registry import build_default_registry


class FinanceEconomicIndicatorsQueryParams(EconomicIndicatorsQueryParams):
    """Finance economic indicators query."""

    pass


class FinanceEconomicIndicatorsData(EconomicIndicatorsData):
    """Finance economic indicators data."""

    pass


class FinanceEconomicIndicatorsFetcher(
    Fetcher[FinanceEconomicIndicatorsQueryParams, list[FinanceEconomicIndicatorsData]]
):
    """Fetcher for economic indicators with multi-source support."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceEconomicIndicatorsQueryParams:
        return FinanceEconomicIndicatorsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceEconomicIndicatorsQueryParams,
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
            if akshare_source and hasattr(akshare_source, "fetch_macro_indicators"):
                start_date = str(query.start_date) if query.start_date else None
                end_date = str(query.end_date) if query.end_date else None
                data = await akshare_source.fetch_macro_indicators(
                    symbol=query.symbol,
                    start_date=start_date,
                    end_date=end_date,
                )
                return data
            return []
        
        # For non-China data, try to use OpenBB built-in providers
        # This requires the openbb package to be installed with relevant extensions
        try:
            if "openbb_client" in kwargs:
                openbb_client = kwargs["openbb_client"]
            else:
                from openbb import obb as openbb_client

            result = openbb_client.economy.indicators(
                symbol=query.symbol,
                country=query.country,
                frequency=query.frequency or "quarter",
                start_date=query.start_date,
                end_date=query.end_date,
                provider="econdb",  # Use econdb as default provider
            )
            if result and hasattr(result, 'results'):
                return [
                    {
                        "date": item.date,
                        "symbol": item.symbol,
                        "symbol_root": item.symbol_root,
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
        query: FinanceEconomicIndicatorsQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceEconomicIndicatorsData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [
            FinanceEconomicIndicatorsData(
                date=_to_date(row["date"]),
                symbol=row.get("symbol"),
                symbol_root=row.get("symbol_root"),
                country=row.get("country"),
                value=row.get("value"),
            )
            for row in data
        ]


def _to_date(value: Any) -> dateType:
    if isinstance(value, dateType):
        return value
    if isinstance(value, str):
        # Handle various date formats
        try:
            return dateType.fromisoformat(value[:10])
        except ValueError:
            # Try parsing YYYY-MM or YYYYMMDD format
            if len(value) == 7:  # YYYY-MM
                return dateType.fromisoformat(value + "-01")
            elif len(value) == 8:  # YYYYMMDD
                return dateType.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:8]}")
    return dateType.today()
