"""Finance unusual options model backed by local database cache."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from datetime import date as dateType
from typing import Any, Literal

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.options_unusual import (
    OptionsUnusualData,
    OptionsUnusualQueryParams,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field, field_validator, model_validator
from shared.database import session_scope
from shared.models.options import OptionsFlow
from sqlalchemy import Select, select


class FinanceOptionsUnusualQueryParams(OptionsUnusualQueryParams):
    """Finance unusual options query."""

    start_date: dateType | None = Field(
        default=None,
        description=QUERY_DESCRIPTIONS.get("start_date", ""),
    )
    end_date: dateType | None = Field(
        default=None,
        description=QUERY_DESCRIPTIONS.get("end_date", ""),
    )
    side: Literal["Bid", "Ask"] | None = Field(
        default=None,
        description="Filter by where the trade prints: 'Bid' = seller-aggressor side, 'Ask' = buyer-aggressor side.",
    )
    option_type: Literal["P", "C"] | None = Field(default=None, description="Option type.")
    min_premium: float | None = Field(default=None, description="Minimum premium in USD.")
    min_vol_oi: float | None = Field(default=None, description="Minimum volume/open-interest ratio.")
    limit: int = Field(default=50, ge=1, le=1000, description=QUERY_DESCRIPTIONS.get("limit", ""))

    @model_validator(mode="before")
    @classmethod
    def validate_dates(cls, values: Any) -> Any:
        """Populate and validate date range."""
        if not isinstance(values, dict):
            return values

        end_date = values.get("end_date") or dateType.today()
        start_date = values.get("start_date") or (end_date - timedelta(days=7))
        if start_date > end_date:
            raise OpenBBError("start_date cannot be after end_date.")
        values["start_date"] = start_date
        values["end_date"] = end_date
        return values


class FinanceOptionsUnusualData(OptionsUnusualData):
    """Finance unusual options data."""

    __alias_dict__ = {
        "underlying_symbol": "symbol",
        "trade_timestamp": "timestamp",
        "average_price": "avg_fill",
        "total_value": "premium",
    }

    trade_timestamp: datetime = Field(description="The datetime of order placement.")
    sentiment: Literal["bullish", "bearish", "neutral"] | None = Field(
        default=None,
        description="Inferred sentiment from trade side.",
    )
    average_price: float = Field(description="Average fill price.")
    total_value: float = Field(description="Total premium value in USD.")
    strike: float = Field(description="Strike price.")
    option_type: Literal["P", "C"] = Field(description="Put or Call.")
    expiration: dateType = Field(description="Expiration date.")
    dte: int = Field(description="Days to expiration.")
    side: Literal["Bid", "Ask"] = Field(
        description=(
            "Where the trade prints relative to the spread: "
            "'Bid' = seller-aggressor side, 'Ask' = buyer-aggressor side."
        ),
    )
    interval_volume: int = Field(description="Interval volume.")
    open_interest: int = Field(description="Open interest.")
    vol_oi: float = Field(description="Volume/open-interest ratio.")
    otm_percent: float = Field(description="Out-of-the-money percentage.")
    bid_percent: int = Field(
        description="Share of this flow on the bid side, as a percentage (0-100).",
    )
    ask_percent: int = Field(
        description="Share of this flow on the ask side, as a percentage (0-100).",
    )
    multileg_percent: float = Field(description="Multi-leg percentage.")
    interval_type: str = Field(description="Interval type.")

    @field_validator("contract_symbol", mode="before", check_fields=False)
    @classmethod
    def normalize_contract_symbol(cls, value: str) -> str:
        """Normalize OCC-like contract symbol."""
        return value.replace(" ", "")


class FinanceOptionsUnusualFetcher(Fetcher[FinanceOptionsUnusualQueryParams, list[FinanceOptionsUnusualData]]):
    """Fetcher for finance unusual options data."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceOptionsUnusualQueryParams:
        """Transform query params."""
        return FinanceOptionsUnusualQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceOptionsUnusualQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Extract raw records from the local database."""
        del credentials, kwargs

        start_dt = datetime.combine(query.start_date, time.min, tzinfo=UTC)
        end_dt = datetime.combine(query.end_date, time.max, tzinfo=UTC)

        stmt: Select[tuple[OptionsFlow]] = select(OptionsFlow).where(
            OptionsFlow.timestamp >= start_dt,
            OptionsFlow.timestamp <= end_dt,
        )

        if query.symbol:
            stmt = stmt.where(OptionsFlow.symbol == query.symbol)
        if query.side:
            stmt = stmt.where(OptionsFlow.side == query.side)
        if query.option_type:
            stmt = stmt.where(OptionsFlow.option_type == query.option_type)
        if query.min_premium is not None:
            stmt = stmt.where(OptionsFlow.premium >= query.min_premium)
        if query.min_vol_oi is not None:
            stmt = stmt.where(OptionsFlow.vol_oi >= query.min_vol_oi)

        stmt = stmt.order_by(OptionsFlow.timestamp.desc()).limit(query.limit)

        async with session_scope() as session:
            result = await session.execute(stmt)
            rows = result.scalars().all()

        return [
            {
                "symbol": row.symbol,
                "contract_symbol": _build_contract_symbol(row.symbol, row.expiry, row.option_type, row.strike),
                "timestamp": row.timestamp,
                "sentiment": _infer_sentiment(row.side, row.option_type),
                "avg_fill": row.avg_fill,
                "premium": row.premium,
                "strike": row.strike,
                "option_type": row.option_type,
                "expiration": row.expiry,
                "dte": row.dte,
                "side": row.side,
                "interval_volume": row.interval_volume,
                "open_interest": row.open_interest,
                "vol_oi": row.vol_oi,
                "otm_percent": row.otm_percent,
                "bid_percent": row.bid_percent,
                "ask_percent": row.ask_percent,
                "multileg_percent": row.multileg_percent,
                "interval_type": row.interval_type,
            }
            for row in rows
        ]

    @staticmethod
    def transform_data(
        query: FinanceOptionsUnusualQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceOptionsUnusualData]:
        """Transform raw records to typed results."""
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceOptionsUnusualData.model_validate(item) for item in data]


# Direction follows the Unusual Whales convention: aggressor is inferred from
# where the trade prints relative to the bid/ask spread, and direction also
# depends on whether the contract is a call or a put.
#   Call @ Ask -> buyer aggressor -> bullish
#   Call @ Bid -> seller aggressor -> bearish
#   Put  @ Ask -> buyer aggressor -> bearish
#   Put  @ Bid -> seller aggressor -> bullish
def _infer_sentiment(side: str, option_type: str | None) -> Literal["bullish", "bearish", "neutral"]:
    is_call = option_type == "C"
    is_put = option_type == "P"
    if side == "Ask":
        return "bullish" if is_call else "bearish" if is_put else "neutral"
    if side == "Bid":
        return "bearish" if is_call else "bullish" if is_put else "neutral"
    return "neutral"


def _build_contract_symbol(symbol: str, expiry: dateType, option_type: str, strike: float) -> str:
    strike_part = int(round(strike * 1000))
    return f"{symbol.upper()}{expiry.strftime('%y%m%d')}{option_type.upper()}{strike_part:08d}"
