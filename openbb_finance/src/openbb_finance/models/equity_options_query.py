"""Free-form SQL against the ConvexValue options_snapshots DuckDB table.

CV's /query endpoint enforces `only SELECT and WITH queries are allowed`
server-side (DDL/DML/DESCRIBE are rejected with HTTP 400), so we pass SQL
straight through without a local allowlist. Use this for cross-contract
aggregations that /chains (single-symbol, per-contract) and /screen
(cross-symbol filtering without aggregation) cannot express: GEX/DEX
rankings, term structure, market-wide PCR, max pain, OI concentration.

Example SQL templates live in the openbb-agent-cli skill under the
options.query command reference; the options_snapshots schema (44 fields)
is also documented there.
"""

from __future__ import annotations

from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from pydantic import Field

from openbb_finance.models._query_coerce import ConvexValueQueryParams
from openbb_finance.sources import convexvalue as cv


class FinanceOptionsQueryQueryParams(ConvexValueQueryParams):
    """Read-only SQL query against options_snapshots."""

    sql: str = Field(
        description=(
            "Read-only SELECT or WITH query against the options_snapshots table. "
            "DDL/DML are rejected server-side."
        )
    )
    max_rows: int = Field(
        default=5000, ge=1, le=50000, description="Result row cap."
    )


class FinanceOptionsQueryData(Data):
    """Result of a /query call: the row list is dynamic (depends on SQL)."""

    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = Field(default=0)
    truncated: bool = Field(default=False, description="True if max_rows cut the result.")
    elapsed_ms: int | None = Field(default=None, description="Server-side elapsed time.")

    model_config = {"extra": "allow"}


class FinanceOptionsQueryFetcher(
    Fetcher[FinanceOptionsQueryQueryParams, list[FinanceOptionsQueryData]]
):
    """Fetcher for ConvexValue /query (aggregate result wrapped in a list)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceOptionsQueryQueryParams:
        return FinanceOptionsQueryQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceOptionsQueryQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del credentials, kwargs
        return await cv.fetch_query(query.sql, max_rows=query.max_rows)

    @staticmethod
    def transform_data(
        query: FinanceOptionsQueryQueryParams,
        data: dict[str, Any],
        **kwargs: Any,
    ) -> list[FinanceOptionsQueryData]:
        del query, kwargs
        if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
            raise cv.ConvexValueError(
                f"ConvexValue query returned unexpected response shape: {data!r}"
            )
        rows = data["rows"]
        # Empty rows is a legitimate successful result (e.g. a SELECT that
        # matches nothing). Return the wrapper so route consumers get a
        # consistent empty-success shape.
        return [FinanceOptionsQueryData(
            rows=rows,
            row_count=data.get("row_count", len(rows)),
            truncated=data.get("truncated", False),
            elapsed_ms=data.get("elapsed_ms"),
        )]
