"""Equity options cross-symbol screener from ConvexValue /screen.

openbb has no standard model for an options screener (the equity screener
covers stock-level attributes, not contract-level). We define a custom
QueryParams with high-frequency predicates plus an `extra_filters` escape
hatch that passes CV-native {field, op, value} dicts straight through.

CV supports the operators: eq, ne, gt, gte, lt, lte, and the cross-field
variants eq_field/ne_field/gt_field/gte_field/lt_field/lte_field. The
predefined params below cover the common cases; anything else goes through
extra_filters.
"""

from __future__ import annotations

from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_finance.models._query_coerce import ConvexValueQueryParams
from openbb_finance.sources import convexvalue as cv

# Default output columns cover the fields a screening caller typically wants.
DEFAULT_COLUMNS: tuple[str, ...] = (
    "ticker",
    "underlying_ticker",
    "expiration_date",
    "strike_price",
    "contract_type",
    "implied_volatility",
    "delta",
    "gamma",
    "theta",
    "vega",
    "open_interest",
    "day_volume",
    "bid",
    "ask",
    "underlying_price",
)


class FinanceOptionsScreenerQueryParams(ConvexValueQueryParams):
    """Options screener query.

    Predefined predicates are translated into CV filter objects and AND-merged
    with any explicit `extra_filters`. Leave a predicate unset to skip it.
    """

    underlying_symbol: str | None = Field(default=None, description="Restrict to one underlying ticker (e.g. SPY).")
    option_type: str | None = Field(default=None, description="'call' or 'put'.")
    min_open_interest: float | None = Field(default=None)
    max_open_interest: float | None = Field(default=None)
    min_volume: float | None = Field(default=None, description="Min day volume.")
    min_iv: float | None = Field(default=None, description="Min implied volatility.")
    max_iv: float | None = Field(default=None, description="Max implied volatility.")
    delta_min: float | None = Field(default=None)
    delta_max: float | None = Field(default=None)
    expiration_date: str | None = Field(default=None, description="YYYY-MM-DD expiration filter.")
    sort_by: str | None = Field(default="open_interest", description="CV field name to sort by.")
    sort_dir: str = Field(default="desc", description="'asc' or 'desc'.")
    limit: int = Field(default=50, ge=1, le=1000)
    columns: list[str] | None = Field(default=None, description="CV fields to return. Defaults to DEFAULT_COLUMNS.")
    extra_filters: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Raw CV filter objects, AND-merged with the predefined predicates. "
            'Each entry is {"field": <cv_field>, "op": <eq|ne|gt|gte|lt|lte|'
            "eq_field|ne_field|gt_field|gte_field|lt_field|lte_field>, "
            '"value": <number|string>}.'
        ),
    )


class FinanceOptionsScreenerData(Data):
    """One contract row from an options screen."""

    ticker: str | None = Field(default=None, description="Option contract symbol.")
    underlying_ticker: str | None = Field(default=None)
    expiration_date: str | None = Field(default=None)
    strike_price: float | None = Field(default=None)
    contract_type: str | None = Field(default=None)
    implied_volatility: float | None = Field(default=None)
    delta: float | None = Field(default=None)
    gamma: float | None = Field(default=None)
    theta: float | None = Field(default=None)
    vega: float | None = Field(default=None)
    open_interest: float | None = Field(default=None)
    day_volume: float | None = Field(default=None)
    bid: float | None = Field(default=None)
    ask: float | None = Field(default=None)
    underlying_price: float | None = Field(default=None)

    model_config = {"extra": "allow"}


class FinanceOptionsScreenerFetcher(Fetcher[FinanceOptionsScreenerQueryParams, list[FinanceOptionsScreenerData]]):
    """Fetcher for ConvexValue options screens."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceOptionsScreenerQueryParams:
        return FinanceOptionsScreenerQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceOptionsScreenerQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del credentials, kwargs
        filters = _build_filters(query)
        sort = [{"field": query.sort_by, "direction": query.sort_dir}] if query.sort_by else None
        return await cv.fetch_screen(
            columns=query.columns or list(DEFAULT_COLUMNS),
            filters=filters,
            sort=sort,
            limit=query.limit,
        )

    @staticmethod
    def transform_data(
        query: FinanceOptionsScreenerQueryParams,
        data: dict[str, Any],
        **kwargs: Any,
    ) -> list[FinanceOptionsScreenerData]:
        del query, kwargs
        columns = data.get("columns", [])
        rows = data.get("rows", [])
        if not rows:
            raise EmptyDataError()
        return [FinanceOptionsScreenerData.model_validate(dict(zip(columns, row, strict=False))) for row in rows]


def _build_filters(query: FinanceOptionsScreenerQueryParams) -> list[dict[str, Any]]:
    """Translate predefined predicates into CV filter objects."""
    filters: list[dict[str, Any]] = []
    # Each tuple: (cv_field, cv_op, value). op is applied verbatim to CV.
    predicates: list[tuple[str, str, Any]] = []
    if query.underlying_symbol:
        predicates.append(("underlying_ticker", "eq", query.underlying_symbol.upper()))
    if query.option_type:
        predicates.append(("contract_type", "eq", query.option_type.lower()))
    if query.min_open_interest is not None:
        predicates.append(("open_interest", "gte", query.min_open_interest))
    if query.max_open_interest is not None:
        predicates.append(("open_interest", "lte", query.max_open_interest))
    if query.min_volume is not None:
        predicates.append(("day_volume", "gte", query.min_volume))
    if query.min_iv is not None:
        predicates.append(("implied_volatility", "gte", query.min_iv))
    if query.max_iv is not None:
        predicates.append(("implied_volatility", "lte", query.max_iv))
    if query.delta_min is not None:
        predicates.append(("delta", "gte", query.delta_min))
    if query.delta_max is not None:
        predicates.append(("delta", "lte", query.delta_max))
    if query.expiration_date:
        predicates.append(("expiration_date", "eq", query.expiration_date))
    for field, op, value in predicates:
        filters.append({"field": field, "op": op, "value": value})
    if query.extra_filters:
        filters.extend(query.extra_filters)
    return filters
