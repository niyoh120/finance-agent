import logging
from typing import Any

import pandas as pd
import pandas_ta as ta
from agno.tools.toolkit import Toolkit

logger = logging.getLogger(__name__)


class TechnicalIndicatorTools(Toolkit):
    def __init__(self, **kwargs):
        tools = [self.compute_indicators]
        instructions = (
            "Use this tool to compute technical indicators from historical close prices. "
            "Provide close prices ordered from oldest to newest."
        )
        super().__init__(
            name="technical_indicator_tools",
            tools=tools,
            instructions=instructions,
            **kwargs,
        )

    def compute_indicators(self, closes: list[float]) -> dict[str, Any]:
        """计算 RSI/MACD/布林带等技术指标.

        Args:
            closes: 按时间升序排列的收盘价列表。

        Returns:
            指标字典，包含 rsi/macd/bbands 等字段。
        """
        if len(closes) < 30:
            logger.warning(
                "not enough data for indicators",
                extra={"count": len(closes), "required": 30},
            )
            return {"error": "not_enough_data", "count": len(closes)}

        series = pd.Series(closes, dtype="float64")

        rsi_series = ta.rsi(series, length=14)
        macd_df = ta.macd(series, fast=12, slow=26, signal=9)
        bbands_df = ta.bbands(series, length=20, std=2)
        sma20 = ta.sma(series, length=20)
        sma50 = ta.sma(series, length=50) if len(series) >= 50 else None

        rsi = _last_value(rsi_series)
        macd = _get_column_value(macd_df, "MACD")
        macd_signal = _get_column_value(macd_df, "MACDs")
        macd_hist = _get_column_value(macd_df, "MACDh")
        bbands_upper = _get_column_value(bbands_df, "BBU")
        bbands_middle = _get_column_value(bbands_df, "BBM")
        bbands_lower = _get_column_value(bbands_df, "BBL")

        trend = _infer_trend(series, sma20, sma50)

        return {
            "rsi": rsi,
            "macd": macd,
            "macd_signal": macd_signal,
            "macd_hist": macd_hist,
            "bbands_upper": bbands_upper,
            "bbands_middle": bbands_middle,
            "bbands_lower": bbands_lower,
            "trend": trend,
        }


def _last_value(series: pd.Series | None) -> float | None:
    if series is None or series.empty:
        return None
    value = series.dropna()
    if value.empty:
        return None
    return float(value.iloc[-1])


def _get_column_value(df: pd.DataFrame | None, prefix: str) -> float | None:
    if df is None or df.empty:
        logger.debug("indicator dataframe empty", extra={"prefix": prefix})
        return None
    matches = [col for col in df.columns if col.startswith(prefix)]
    if not matches:
        logger.debug(
            "indicator column missing", extra={"prefix": prefix, "columns": df.columns}
        )
        return None
    logger.debug(
        "indicator column selected", extra={"prefix": prefix, "column": matches[0]}
    )
    return _last_value(df[matches[0]])


def _infer_trend(
    closes: pd.Series, sma20: pd.Series | None, sma50: pd.Series | None
) -> str | None:
    if closes.empty or sma20 is None or sma20.empty:
        return None

    close = float(closes.iloc[-1])
    sma20_value = _last_value(sma20)
    sma50_value = _last_value(sma50) if sma50 is not None else None

    if sma20_value is None:
        return None

    if sma50_value is None:
        return "uptrend" if close >= sma20_value else "downtrend"

    if close >= sma20_value >= sma50_value:
        return "uptrend"
    if close <= sma20_value <= sma50_value:
        return "downtrend"
    return "sideways"
