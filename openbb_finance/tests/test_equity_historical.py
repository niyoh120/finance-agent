from datetime import date
from types import SimpleNamespace

import pytest
from openbb_finance.models.equity_historical import (
    FinanceEquityHistoricalData,
    FinanceEquityHistoricalFetcher,
    FinanceEquityHistoricalQueryParams,
)


class FakeRegistry:
    def ordered_by_names(self, names):
        # Eastmoney is now included in the routing
        assert names == ["tdx", "baostock", "eastmoney", "tickflow", "akshare"]
        return [
            SimpleNamespace(
                name="tdx",
                fetch_price=self.fetch_price,
            )
        ]

    async def fetch_price(self, query):
        return [
            {
                "symbol": query.symbol,
                "date": date(2026, 4, 24),
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 100,
                "source": "tdx",
            }
        ]


@pytest.mark.anyio
async def test_equity_historical_uses_routed_source():
    data = await FinanceEquityHistoricalFetcher.aextract_data(
        FinanceEquityHistoricalQueryParams(
            symbol="600519.XSHG",
            start_date=date(2026, 4, 24),
            end_date=date(2026, 4, 24),
        ),
        credentials=None,
        registry=FakeRegistry(),
    )

    result = FinanceEquityHistoricalFetcher.transform_data(
        FinanceEquityHistoricalQueryParams(symbol="600519.XSHG"),
        data,
    )

    assert len(result) == 1
    assert isinstance(result[0], FinanceEquityHistoricalData)
    assert result[0].symbol == "600519.XSHG"
    assert result[0].source == "tdx"
