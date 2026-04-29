"""Economic calendar aggregated from multiple sources."""

from __future__ import annotations

from datetime import date as dateType
from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.economic_calendar import (
    EconomicCalendarData,
    EconomicCalendarQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError

from openbb_finance.aggregator import aggregate_records
from openbb_finance.registry import build_default_registry


class FinanceEconomicCalendarFetcher(Fetcher[EconomicCalendarQueryParams, list[EconomicCalendarData]]):
    """Fetcher for priority-merged economic calendar data."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> EconomicCalendarQueryParams:
        return EconomicCalendarQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: EconomicCalendarQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials
        registry = kwargs.get("registry") or build_default_registry()
        sources = registry.ordered_by_names(["futunn", "akshare", "openbb"])
        start_date = query.start_date or dateType.today()
        end_date = query.end_date or start_date

        async def fetch(source: Any) -> list[dict[str, Any]]:
            if hasattr(source, "fetch_economic_calendar"):
                return await source.fetch_economic_calendar(start_date, end_date)
            return []

        return await aggregate_records(sources, fetch, key_fields=("date", "country", "event"))

    @staticmethod
    def transform_data(
        query: EconomicCalendarQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[EconomicCalendarData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [
            EconomicCalendarData(
                date=_to_date(row["date"]),
                country=row.get("country", ""),
                category=row.get("category"),
                event=row.get("event", ""),
                importance=row.get("importance"),
                source=row.get("source"),
                actual=row.get("actual"),
                consensus=row.get("consensus"),
                previous=row.get("previous"),
            )
            for row in data
        ]


def _to_date(value: Any) -> dateType:
    if isinstance(value, dateType):
        return value
    return dateType.fromisoformat(str(value)[:10])
