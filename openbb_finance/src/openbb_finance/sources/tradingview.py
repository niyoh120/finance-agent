"""TradingView screener data source using tvscreener library."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

import pandas as pd

ScreenerMarket = Literal["america", "hongkong", "china", "global"]

# Default fields to return
DEFAULT_FIELDS = [
    "DESCRIPTION",
    "SYMBOL",
    "PRICE",
    "CHANGE_PERCENT",
    "VOLUME",
    "MARKET_CAPITALIZATION",
    "SECTOR",
    "RELATIVE_STRENGTH_INDEX_14",
]

# Column name mapping from tvscreener labels to our field names
COLUMN_MAPPING = {
    "Description": "name",
    "Symbol": "symbol",
    "Price": "price",
    "Change %": "change_percent",
    "Volume": "volume",
    "Market Capitalization": "market_cap",
    "Sector": "sector",
    "Relative Strength Index (14)": "rsi",
}


def _stock_fields(field_names: list[str]) -> list[Any]:
    """Resolve StockField names to tvscreener fields."""
    from tvscreener import StockField

    resolved = []
    for field_name in field_names:
        normalized = field_name.upper()
        if normalized == "SYMBOL":
            continue
        field = getattr(StockField, normalized, None)
        if field is None:
            raise ValueError(f"Unknown field: {field_name}")
        resolved.append(field)
    return resolved


def _apply_filter(
    screener: Any,
    field_name: str,
    conditions: dict[str, Any],
) -> None:
    """Apply a filter condition to the screener.

    Args:
        screener: StockScreener instance
        field_name: StockField enum name (e.g., "PRICE", "VOLUME")
        conditions: Dict with "min", "max", "in" keys
    """
    field = _stock_fields([field_name])[0]

    # Apply conditions
    if "min" in conditions and "max" in conditions:
        screener.where(field.between(conditions["min"], conditions["max"]))
    elif "min" in conditions:
        screener.where(field >= conditions["min"])
    elif "max" in conditions:
        screener.where(field <= conditions["max"])

    if "in" in conditions:
        screener.where(field.isin(conditions["in"]))


def _run_screener(
    market: ScreenerMarket | None = None,
    limit: int = 150,
    price_min: float | None = None,
    price_max: float | None = None,
    change_percent_min: float | None = None,
    change_percent_max: float | None = None,
    volume_min: int | None = None,
    volume_max: int | None = None,
    market_cap_min: float | None = None,
    market_cap_max: float | None = None,
    rsi_min: float | None = None,
    rsi_max: float | None = None,
    sector: list[str] | None = None,
    filters: dict[str, dict[str, Any]] | None = None,
    fields: list[str] | None = None,
) -> pd.DataFrame:
    """同步执行 TradingView 筛选器."""
    from tvscreener import Market as TVMarket
    from tvscreener import StockScreener

    ss = StockScreener()
    requested_fields = fields or DEFAULT_FIELDS
    select_fields = _stock_fields(requested_fields)
    if select_fields:
        ss.select(*select_fields)
    ss.set_range(0, max(limit, 0))

    # Set market
    if market:
        market_map = {
            "america": TVMarket.AMERICA,
            "hongkong": TVMarket.HONGKONG,
            "china": TVMarket.CHINA,
            "global": TVMarket.ALL,
        }
        tv_market = market_map.get(market)
        if tv_market:
            ss.set_markets(tv_market)

    # Apply simple filters (backward compatible)
    if price_min is not None or price_max is not None:
        conditions = {}
        if price_min is not None:
            conditions["min"] = price_min
        if price_max is not None:
            conditions["max"] = price_max
        _apply_filter(ss, "PRICE", conditions)

    if change_percent_min is not None or change_percent_max is not None:
        conditions = {}
        if change_percent_min is not None:
            conditions["min"] = change_percent_min
        if change_percent_max is not None:
            conditions["max"] = change_percent_max
        _apply_filter(ss, "CHANGE_PERCENT", conditions)

    if volume_min is not None or volume_max is not None:
        conditions = {}
        if volume_min is not None:
            conditions["min"] = volume_min
        if volume_max is not None:
            conditions["max"] = volume_max
        _apply_filter(ss, "VOLUME", conditions)

    if market_cap_min is not None or market_cap_max is not None:
        conditions = {}
        if market_cap_min is not None:
            conditions["min"] = market_cap_min
        if market_cap_max is not None:
            conditions["max"] = market_cap_max
        _apply_filter(ss, "MARKET_CAPITALIZATION", conditions)

    if rsi_min is not None or rsi_max is not None:
        conditions = {}
        if rsi_min is not None:
            conditions["min"] = rsi_min
        if rsi_max is not None:
            conditions["max"] = rsi_max
        _apply_filter(ss, "RELATIVE_STRENGTH_INDEX_14", conditions)

    if sector:
        _apply_filter(ss, "SECTOR", {"in": sector})

    # Apply advanced filters
    if filters:
        for field_name, conditions in filters.items():
            _apply_filter(ss, field_name.upper(), conditions)

    df = ss.get()

    if len(df) > limit:
        df = df.head(limit)

    return df


def _normalize_dataframe(
    df: pd.DataFrame,
    fields: list[str] | None = None,
) -> list[dict[str, Any]]:
    """将 DataFrame 转换为标准化的字典列表."""
    if df.empty:
        return []

    # Determine which columns to keep
    if fields:
        # Map field names to column names
        from tvscreener import StockField

        keep_columns = ["Symbol"] if "Symbol" in df.columns else []
        for f in fields:
            normalized = f.upper()
            if normalized == "SYMBOL":
                continue
            field = getattr(StockField, normalized, None)
            if field is None:
                raise ValueError(f"Unknown field: {f}")
            label = field.label
            if label in df.columns:
                keep_columns.append(label)
    else:
        # Use default columns
        keep_columns = [c for c in COLUMN_MAPPING.keys() if c in df.columns]

    df = df[keep_columns].copy()
    df = df.rename(columns=COLUMN_MAPPING)

    results = []
    for _, row in df.iterrows():
        record = {}
        for col in df.columns:
            val = row[col]
            if pd.isna(val):
                record[col] = None
            elif isinstance(val, (int, float, str)):
                record[col] = val
            else:
                record[col] = str(val)
        results.append(record)

    return results


async def fetch_equity_screener(
    market: ScreenerMarket | None = None,
    limit: int = 150,
    price_min: float | None = None,
    price_max: float | None = None,
    change_percent_min: float | None = None,
    change_percent_max: float | None = None,
    volume_min: int | None = None,
    volume_max: int | None = None,
    market_cap_min: float | None = None,
    market_cap_max: float | None = None,
    rsi_min: float | None = None,
    rsi_max: float | None = None,
    sector: list[str] | None = None,
    filters: dict[str, dict[str, Any]] | None = None,
    fields: list[str] | None = None,
) -> list[dict[str, Any]]:
    """异步获取股票筛选结果."""
    df = await asyncio.to_thread(
        _run_screener,
        market,
        limit,
        price_min,
        price_max,
        change_percent_min,
        change_percent_max,
        volume_min,
        volume_max,
        market_cap_min,
        market_cap_max,
        rsi_min,
        rsi_max,
        sector,
        filters,
        fields,
    )
    return _normalize_dataframe(df, fields)
