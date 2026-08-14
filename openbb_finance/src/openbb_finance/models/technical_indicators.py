"""Technical indicators computed from routed historical prices."""

from __future__ import annotations

from datetime import date as dateType
from datetime import datetime
from typing import Any, Literal

import pandas as pd
from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field, field_validator

from openbb_finance.models.equity_historical import (
    FinanceEquityHistoricalFetcher,
    FinanceEquityHistoricalQueryParams,
)

IndicatorName = Literal["rsi", "macd", "sma", "ema", "bbands", "atr", "stoch", "vwap"]


class FinanceTechnicalIndicatorsQueryParams(QueryParams):
    """Finance technical indicators query."""

    symbol: str = Field(description="Symbol to get technical indicators for.")
    start_date: dateType | None = Field(default=None, description="Start date of the historical data.")
    end_date: dateType | None = Field(default=None, description="End date of the historical data.")
    interval: str = Field(default="1d", description="Price interval, e.g. 1d, 1w, 5m, 15m, 30m, 60m.")
    adjusted: bool = Field(default=False, description="Whether to request adjusted prices.")
    indicators: list[IndicatorName] = Field(
        default_factory=lambda: ["rsi", "macd", "sma", "ema", "bbands", "atr", "stoch", "vwap"],
        description="Technical indicators to compute.",
    )
    rsi_length: int = Field(default=14, ge=1, description="RSI lookback period.")
    macd_fast: int = Field(default=12, ge=1, description="MACD fast EMA period.")
    macd_slow: int = Field(default=26, ge=1, description="MACD slow EMA period.")
    macd_signal: int = Field(default=9, ge=1, description="MACD signal EMA period.")
    sma_lengths: list[int] = Field(default_factory=lambda: [20, 50], description="SMA periods to compute.")
    ema_lengths: list[int] = Field(default_factory=lambda: [20], description="EMA periods to compute.")
    bbands_length: int = Field(default=20, ge=1, description="Bollinger Bands lookback period.")
    bbands_std: float = Field(default=2.0, gt=0, description="Bollinger Bands standard deviation multiplier.")
    atr_length: int = Field(default=14, ge=1, description="ATR lookback period.")
    stoch_k: int = Field(default=14, ge=1, description="Stochastic oscillator K period.")
    stoch_d: int = Field(default=3, ge=1, description="Stochastic oscillator D period.")

    @field_validator("sma_lengths", "ema_lengths")
    @classmethod
    def validate_lengths(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("At least one period is required.")
        if any(length < 1 for length in value):
            raise ValueError("All periods must be positive.")
        return value


class FinanceTechnicalIndicatorsData(Data):
    """Finance technical indicators data."""

    date: dateType | datetime = Field(description="Date of the observation.")
    open: float = Field(description="Open price.")
    high: float = Field(description="High price.")
    low: float = Field(description="Low price.")
    close: float = Field(description="Close price.")
    volume: int | float | None = Field(default=None, description="Trading volume.")
    symbol: str | None = Field(default=None, description="Requested symbol.")
    source: str | None = Field(default=None, description="Selected data source.")
    rsi: float | None = Field(default=None, description="Relative Strength Index.")
    macd: float | None = Field(default=None, description="MACD line.")
    macd_signal: float | None = Field(default=None, description="MACD signal line.")
    macd_histogram: float | None = Field(default=None, description="MACD histogram.")
    sma_20: float | None = Field(default=None, description="20-period simple moving average.")
    sma_50: float | None = Field(default=None, description="50-period simple moving average.")
    ema_20: float | None = Field(default=None, description="20-period exponential moving average.")
    bbands_upper: float | None = Field(default=None, description="Bollinger Bands upper band.")
    bbands_middle: float | None = Field(default=None, description="Bollinger Bands middle band.")
    bbands_lower: float | None = Field(default=None, description="Bollinger Bands lower band.")
    atr: float | None = Field(default=None, description="Average True Range.")
    stoch_k: float | None = Field(default=None, description="Stochastic oscillator K value.")
    stoch_d: float | None = Field(default=None, description="Stochastic oscillator D value.")
    vwap: float | None = Field(default=None, description="Volume weighted average price.")


class FinanceTechnicalIndicatorsFetcher(
    Fetcher[FinanceTechnicalIndicatorsQueryParams, list[FinanceTechnicalIndicatorsData]]
):
    """Fetcher for technical indicators computed from routed historical prices."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FinanceTechnicalIndicatorsQueryParams:
        return FinanceTechnicalIndicatorsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FinanceTechnicalIndicatorsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        price_query = FinanceEquityHistoricalQueryParams(
            symbol=query.symbol,
            start_date=query.start_date,
            end_date=query.end_date,
            interval=query.interval,
            adjusted=query.adjusted,
        )
        rows = await FinanceEquityHistoricalFetcher.aextract_data(
            price_query,
            credentials=credentials,
            **kwargs,
        )
        if not rows:
            return []

        frame = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
        _compute_indicators(frame, query)
        return [_clean_record(record) for record in frame.to_dict("records")]

    @staticmethod
    def transform_data(
        query: FinanceTechnicalIndicatorsQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FinanceTechnicalIndicatorsData]:
        del query, kwargs
        if not data:
            raise EmptyDataError()
        return [FinanceTechnicalIndicatorsData.model_validate(row) for row in data]


def _compute_indicators(frame: pd.DataFrame, query: FinanceTechnicalIndicatorsQueryParams) -> None:
    close = pd.to_numeric(frame["close"], errors="coerce")
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    volume = pd.to_numeric(frame["volume"], errors="coerce") if "volume" in frame else None

    if "rsi" in query.indicators:
        frame["rsi"] = _rsi(close, query.rsi_length)

    if "macd" in query.indicators:
        macd = (
            close.ewm(span=query.macd_fast, adjust=False, min_periods=query.macd_fast).mean()
            - close.ewm(
                span=query.macd_slow,
                adjust=False,
                min_periods=query.macd_slow,
            ).mean()
        )
        signal = macd.ewm(span=query.macd_signal, adjust=False, min_periods=query.macd_signal).mean()
        frame["macd"] = macd
        frame["macd_signal"] = signal
        frame["macd_histogram"] = macd - signal

    if "sma" in query.indicators:
        for length in query.sma_lengths:
            frame[f"sma_{length}"] = close.rolling(length, min_periods=length).mean()

    if "ema" in query.indicators:
        for length in query.ema_lengths:
            frame[f"ema_{length}"] = close.ewm(span=length, adjust=False, min_periods=length).mean()

    if "bbands" in query.indicators:
        middle = close.rolling(query.bbands_length, min_periods=query.bbands_length).mean()
        deviation = close.rolling(query.bbands_length, min_periods=query.bbands_length).std()
        frame["bbands_middle"] = middle
        frame["bbands_upper"] = middle + query.bbands_std * deviation
        frame["bbands_lower"] = middle - query.bbands_std * deviation

    if "atr" in query.indicators:
        previous_close = close.shift(1)
        true_range = pd.concat(
            [(high - low), (high - previous_close).abs(), (low - previous_close).abs()],
            axis=1,
        ).max(axis=1)
        frame["atr"] = true_range.rolling(query.atr_length, min_periods=query.atr_length).mean()

    if "stoch" in query.indicators:
        low_min = low.rolling(query.stoch_k, min_periods=query.stoch_k).min()
        high_max = high.rolling(query.stoch_k, min_periods=query.stoch_k).max()
        stoch_k = 100 * (close - low_min) / (high_max - low_min)
        frame["stoch_k"] = stoch_k
        frame["stoch_d"] = stoch_k.rolling(query.stoch_d, min_periods=query.stoch_d).mean()

    if "vwap" in query.indicators and volume is not None:
        typical_price = (high + low + close) / 3
        cumulative_volume = volume.cumsum()
        frame["vwap"] = (typical_price * volume).cumsum() / cumulative_volume.where(cumulative_volume != 0)


def _rsi(close: pd.Series, length: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    average_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    average_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    rs = average_gain / average_loss
    return 100 - (100 / (1 + rs))


def _clean_record(record: dict[str, Any]) -> dict[str, Any]:
    return {key: _clean_value(value) for key, value in record.items()}


def _clean_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value
