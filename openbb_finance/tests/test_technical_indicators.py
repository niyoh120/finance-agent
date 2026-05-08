from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from openbb_finance.models.technical_indicators import (
    FinanceTechnicalIndicatorsData,
    FinanceTechnicalIndicatorsFetcher,
    FinanceTechnicalIndicatorsQueryParams,
)

from openbb_finance import provider


class FakeRegistry:
    def ordered_by_names(self, names):
        assert names == ["tdx", "baostock", "eastmoney", "tickflow", "akshare"]
        return [
            SimpleNamespace(
                name="tdx",
                fetch_price=self.fetch_price,
            )
        ]

    async def fetch_price(self, query):
        start = date(2026, 1, 1)
        return [
            {
                "symbol": query.symbol,
                "date": start + timedelta(days=index),
                "open": 100 + index,
                "high": 101 + index,
                "low": 99 + index,
                "close": 100 + index,
                "volume": 1000 + index,
                "source": "tdx",
            }
            for index in range(60)
        ]


@pytest.mark.anyio
async def test_technical_indicators_are_computed_from_routed_prices():
    query = FinanceTechnicalIndicatorsQueryParams(
        symbol="600519.XSHG",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 3, 1),
        indicators=["rsi", "macd", "sma", "ema", "bbands", "atr", "stoch", "vwap"],
    )

    data = await FinanceTechnicalIndicatorsFetcher.aextract_data(
        query,
        credentials=None,
        registry=FakeRegistry(),
    )
    result = FinanceTechnicalIndicatorsFetcher.transform_data(query, data)

    assert len(result) == 60
    row = result[-1]
    assert isinstance(row, FinanceTechnicalIndicatorsData)
    assert row.symbol == "600519.XSHG"
    assert row.source == "tdx"
    assert row.rsi == pytest.approx(100)
    assert row.macd is not None
    assert row.macd_signal is not None
    assert row.macd_histogram is not None
    assert row.sma_20 == pytest.approx(149.5)
    assert row.sma_50 == pytest.approx(134.5)
    assert row.ema_20 is not None
    assert row.bbands_upper is not None
    assert row.bbands_middle == pytest.approx(149.5)
    assert row.bbands_lower is not None
    assert row.atr == pytest.approx(2)
    assert row.stoch_k == pytest.approx(93.3333333333)
    assert row.stoch_d == pytest.approx(93.3333333333)
    expected_vwap = sum((100 + index) * (1000 + index) for index in range(60)) / sum(
        1000 + index for index in range(60)
    )
    assert row.vwap == pytest.approx(expected_vwap)


def test_technical_indicators_fetcher_registered():
    assert provider.fetcher_dict["TechnicalIndicators"] is FinanceTechnicalIndicatorsFetcher


def test_technical_indicators_preserve_intraday_datetime():
    moment = datetime(2026, 5, 6, 9, 35)
    result = FinanceTechnicalIndicatorsFetcher.transform_data(
        FinanceTechnicalIndicatorsQueryParams(symbol="600519.XSHG", interval="5m"),
        [
            {
                "date": moment,
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 100,
                "symbol": "600519.XSHG",
                "source": "tdx",
                "rsi": 55.0,
            }
        ],
    )

    assert result[0].date == moment
