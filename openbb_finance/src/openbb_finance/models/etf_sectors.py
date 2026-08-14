"""ETF sector weightings from ConvexValue /fmp/stable/etf/sector-weightings."""

from __future__ import annotations

from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.etf_sectors import (
    EtfSectorsData,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.models._query_coerce import ConvexValueQueryParams
from openbb_finance.sources import convexvalue as cv


class FinanceEtfSectorsQueryParams(ConvexValueQueryParams):
    """ETF sector weightings query."""

    symbol: str = Field(description=QUERY_DESCRIPTIONS.get("symbol", ""))


class FinanceEtfSectorsData(EtfSectorsData):
    """ETF sector weighting row."""

    __alias_dict__ = {
        "weight": "weightPercentage",
    }

    weight: float = Field(description="Sector weight (percentage).")


class FinanceEtfSectorsFetcher(Fetcher[FinanceEtfSectorsQueryParams, list[FinanceEtfSectorsData]]):
    """Fetcher for ConvexValue/FMP ETF sector weightings."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceEtfSectorsQueryParams:
        return FinanceEtfSectorsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceEtfSectorsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials, kwargs
        return await cv.fetch_fmp("etf/sector-weightings", symbol=query.symbol)

    @staticmethod
    def transform_data(
        query: FinanceEtfSectorsQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceEtfSectorsData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceEtfSectorsData.model_validate(row) for row in data]
