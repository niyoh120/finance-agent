"""Available economic indicators for finance provider."""

from __future__ import annotations

from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.available_indicators import (
    AvailableIndicatorsData,
    AvailableIndicesQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError

_CHINA_MACRO_INDICATORS = [
    {
        "symbol_root": "GDP",
        "symbol": "GDP",
        "country": "china",
        "iso": "CHN",
        "description": "China nominal gross domestic product, quarterly absolute value.",
        "frequency": "quarter",
    },
    {
        "symbol_root": "GDP",
        "symbol": "GDP_YOY",
        "country": "china",
        "iso": "CHN",
        "description": "China GDP year-over-year growth rate release.",
        "frequency": "quarter",
    },
    {
        "symbol_root": "CPI",
        "symbol": "CPI",
        "country": "china",
        "iso": "CHN",
        "description": "China consumer price index.",
        "frequency": "month",
    },
    {
        "symbol_root": "CPI",
        "symbol": "CPI_YOY",
        "country": "china",
        "iso": "CHN",
        "description": "China CPI year-over-year growth rate release.",
        "frequency": "month",
    },
    {
        "symbol_root": "PPI",
        "symbol": "PPI",
        "country": "china",
        "iso": "CHN",
        "description": "China producer price index.",
        "frequency": "month",
    },
    {
        "symbol_root": "PMI",
        "symbol": "PMI",
        "country": "china",
        "iso": "CHN",
        "description": "China manufacturing purchasing managers index.",
        "frequency": "month",
    },
]


def _normalize_indicator_row(row: Any) -> dict[str, Any]:
    """Normalize OpenBB models and dictionaries into AvailableIndicators fields."""
    if hasattr(row, "model_dump"):
        values = row.model_dump()
    elif isinstance(row, dict):
        values = row
    else:
        values = {field: getattr(row, field, None) for field in AvailableIndicatorsData.model_fields}

    return {field: values.get(field) for field in AvailableIndicatorsData.model_fields}


def _dedupe_indicator_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        key = (
            row.get("symbol_root"),
            row.get("symbol"),
            row.get("country"),
            row.get("iso"),
            row.get("frequency"),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


class FinanceAvailableIndicatorsQueryParams(AvailableIndicesQueryParams):
    """Finance available economic indicators query."""

    pass


class FinanceAvailableIndicatorsData(AvailableIndicatorsData):
    """Finance available economic indicators data."""

    pass


class FinanceAvailableIndicatorsFetcher(
    Fetcher[FinanceAvailableIndicatorsQueryParams, list[FinanceAvailableIndicatorsData]]
):
    """Fetcher for finance provider economic indicator metadata."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceAvailableIndicatorsQueryParams:
        return FinanceAvailableIndicatorsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceAvailableIndicatorsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del query, credentials
        rows = [_normalize_indicator_row(row) for row in _CHINA_MACRO_INDICATORS]
        openbb_client = kwargs["openbb_client"] if "openbb_client" in kwargs else None

        if "openbb_client" not in kwargs:
            try:
                from openbb import obb as openbb_client
            except Exception:
                openbb_client = None

        if openbb_client is not None:
            for provider in ("econdb", "imf"):
                try:
                    response = openbb_client.economy.available_indicators(provider=provider)
                except Exception:
                    continue

                for row in getattr(response, "results", []) or []:
                    rows.append(_normalize_indicator_row(row))

        return _dedupe_indicator_rows(rows)

    @staticmethod
    def transform_data(
        query: FinanceAvailableIndicatorsQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceAvailableIndicatorsData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceAvailableIndicatorsData(**row) for row in data]
