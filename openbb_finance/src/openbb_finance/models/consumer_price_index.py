"""Consumer Price Index (CPI) data with multi-source aggregation."""

from __future__ import annotations

from datetime import date as dateType
from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.consumer_price_index import (
    ConsumerPriceIndexData,
    ConsumerPriceIndexQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError

from openbb_finance.registry import build_default_registry


class FinanceConsumerPriceIndexQueryParams(ConsumerPriceIndexQueryParams):
    """Finance CPI query."""

    pass


class FinanceConsumerPriceIndexData(ConsumerPriceIndexData):
    """Finance CPI data."""

    pass


class FinanceConsumerPriceIndexFetcher(
    Fetcher[FinanceConsumerPriceIndexQueryParams, list[FinanceConsumerPriceIndexData]]
):
    """Fetcher for CPI data with multi-source support."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceConsumerPriceIndexQueryParams:
        return FinanceConsumerPriceIndexQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceConsumerPriceIndexQueryParams,
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
            if akshare_source and hasattr(akshare_source, "fetch_macro_cpi"):
                data = await akshare_source.fetch_macro_cpi(transform=query.transform)
                # Transform to match CPI format
                rows = [
                    {
                        "date": row["date"],
                        "country": "china",
                        "value": row.get("value"),
                        "source": "akshare",
                    }
                    for row in data
                ]
                if query.frequency == "annual":
                    rows = _aggregate_annual(rows)
                return _filter_date_range(rows, query.start_date, query.end_date)
            return []

        # For non-China data, try to use OpenBB built-in providers
        try:
            from openbb import obb

            result = obb.economy.cpi(
                country=query.country,
                transform=query.transform,
                frequency=query.frequency,
                harmonized=query.harmonized,
                start_date=query.start_date,
                end_date=query.end_date,
                provider="oecd",  # Use OECD as default provider for international data
            )
            if result and hasattr(result, "results"):
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
        query: FinanceConsumerPriceIndexQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceConsumerPriceIndexData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [
            FinanceConsumerPriceIndexData(
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


def _aggregate_annual(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_year: dict[int, list[dict[str, Any]]] = {}
    for row in data:
        by_year.setdefault(_to_date(row["date"]).year, []).append(row)

    rows: list[dict[str, Any]] = []
    for year in sorted(by_year):
        values = [row.get("value") for row in by_year[year] if row.get("value") is not None]
        rows.append(
            {
                **by_year[year][-1],
                "date": f"{year}-12-31",
                "value": sum(values) / len(values) if values else None,
            }
        )
    return rows
