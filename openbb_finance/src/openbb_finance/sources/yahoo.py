"""Yahoo Finance source via OpenBB when available."""

from __future__ import annotations

from typing import Any

from openbb_finance.config import SourceConfig
from openbb_finance.sources.base import DataType, Market, PriceQuery, SourceError
from openbb_finance.sources.symbols import is_cn_symbol, to_openbb_symbol, to_yfinance_symbol


class YahooSource:
    name = "yahoo"

    def __init__(self, config: SourceConfig) -> None:
        self.enabled = config.enabled
        self.priority = config.priority

    def supports(self, market: Market, data_type: DataType, **kwargs: Any) -> bool:
        del kwargs
        return market in {"us", "hk"} and data_type in {"price", "fundamental"}

    async def fetch_quote(self, symbol: str) -> dict[str, Any]:
        try:
            from openbb import obb
        except ImportError as exc:
            raise SourceError("OpenBB package is required for Yahoo source") from exc

        yfinance_symbol = to_yfinance_symbol(symbol)
        result = obb.equity.price.quote(symbol=yfinance_symbol, provider="yfinance")
        if not result.results:
            raise SourceError("Yahoo returned empty quote")
        row = result.results[0].model_dump()
        row["symbol"] = to_openbb_symbol(symbol) if is_cn_symbol(symbol) else row.get("symbol") or symbol
        row["source"] = "yahoo"
        return row

    async def fetch_price(self, query: PriceQuery) -> list[dict[str, Any]]:
        try:
            from openbb import obb
        except ImportError as exc:
            raise SourceError("OpenBB package is required for Yahoo source") from exc

        result = obb.equity.price.historical(
            symbol=to_yfinance_symbol(query.symbol),
            start_date=query.start_date,
            end_date=query.end_date,
            provider="yfinance",
        )
        df = result.to_df()
        if df.empty:
            raise SourceError("Yahoo returned empty data")
        rows: list[dict[str, Any]] = []
        for index, row in df.reset_index().iterrows():
            date_value = row.get("date") or row.get("Date") or index
            rows.append(
                {
                    "symbol": to_openbb_symbol(query.symbol),
                    "date": date_value,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]) if row.get("volume") is not None else None,
                    "source": "yahoo",
                }
            )
        return rows
