from datetime import date, datetime

import pytest
from openbb_finance.config import SourceConfig
from openbb_finance.sources.base import PriceQuery, SourceError
from openbb_finance.sources.tdx import TdxSource, _to_tdx_code, _to_tdx_interval, _to_tdx_search_keyword

pytestmark = pytest.mark.anyio


def test_tdx_symbol_mapping():
    assert _to_tdx_code("600519.XSHG") == "600519"
    assert _to_tdx_code("000001.SZ") == "000001"
    with pytest.raises(SourceError):
        _to_tdx_code("AAPL")


def test_tdx_interval_mapping():
    assert _to_tdx_interval("1") == "minute1"
    assert _to_tdx_interval("5m") == "minute5"
    assert _to_tdx_interval("60") == "hour"
    assert _to_tdx_interval("1d") == "day"
    assert _to_tdx_interval("1w") == "week"
    assert _to_tdx_interval("1M") == "month"


async def test_tdx_quote_normalizes_payload():
    class FakeTdxSource(TdxSource):
        async def _get(self, path, params=None):
            assert path == "/api/quote"
            assert params == {"code": "000001"}
            return {
                "code": 0,
                "message": "success",
                "data": [
                    {
                        "Code": "000001",
                        "K": {"Last": 11360, "Open": 11370, "High": 11390, "Low": 11300, "Close": 11310},
                        "TotalHand": 502044,
                    }
                ],
            }

    source = FakeTdxSource(SourceConfig(name="tdx", enabled=True, priority=110))
    result = await source.fetch_quote("000001.XSHE")

    assert result["symbol"] == "000001.XSHE"
    assert result["last_price"] == 11.31
    assert result["prev_close"] == 11.36
    assert result["open"] == 11.37
    assert result["volume"] == 50204400
    assert result["change"] == pytest.approx(-0.05)
    assert result["change_percent"] == pytest.approx(-0.4401408450704266)
    assert result["source"] == "tdx"


async def test_tdx_price_normalizes_kline_history():
    class FakeTdxSource(TdxSource):
        async def _get(self, path, params=None):
            assert path == "/api/kline-all/tdx"
            assert params == {
                "code": "000001",
                "type": "day",
            }
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "Count": 1,
                    "List": [
                        {
                            "Last": 12950,
                            "Open": 12910,
                            "High": 13040,
                            "Low": 12540,
                            "Close": 12590,
                            "Volume": 1269423,
                            "Amount": 0,
                            "Time": "2023-01-10T15:00:00+08:00",
                        },
                        {
                            "Last": 11490,
                            "Open": 11500,
                            "High": 11500,
                            "Low": 11300,
                            "Close": 11360,
                            "Volume": 1216388,
                            "Amount": 0,
                            "Time": "2026-05-06T15:00:00+08:00",
                        }
                    ],
                },
            }

    source = FakeTdxSource(SourceConfig(name="tdx", enabled=True, priority=110))
    result = await source.fetch_price(
        PriceQuery(
            symbol="000001.XSHE",
            market="cn",
            start_date=date(2026, 4, 30),
            end_date=date(2026, 5, 6),
        )
    )

    assert result == [
        {
            "symbol": "000001.XSHE",
            "date": datetime.fromisoformat("2026-05-06T15:00:00+08:00"),
            "open": 11.5,
            "high": 11.5,
            "low": 11.3,
            "close": 11.36,
            "volume": 121638800.0,
            "amount": 0.0,
            "source": "tdx",
        }
    ]


async def test_tdx_adjusted_price_uses_ths_kline_source():
    class FakeTdxSource(TdxSource):
        async def _get(self, path, params=None):
            assert path == "/api/kline-all/ths"
            assert params == {"code": "000001", "type": "week"}
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "count": 1,
                    "list": [
                        {
                            "Open": 11500,
                            "High": 11500,
                            "Low": 11300,
                            "Close": 11360,
                            "Volume": 1216388,
                            "Amount": 0,
                            "Time": "2026-05-06T15:00:00+08:00",
                        }
                    ],
                },
            }

    source = FakeTdxSource(SourceConfig(name="tdx", enabled=True, priority=110))
    result = await source.fetch_price(
        PriceQuery(symbol="000001.XSHE", market="cn", interval="1w", adjusted=True)
    )

    assert result[0]["source"] == "tdx"
    assert result[0]["close"] == 11.36


async def test_tdx_adjusted_intraday_applies_baostock_forward_factor():
    class FakeTdxSource(TdxSource):
        async def _get(self, path, params=None):
            assert path == "/api/kline-all/tdx"
            assert params == {"code": "000001", "type": "minute5"}
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "List": [
                        {
                            "Open": 10000,
                            "High": 11000,
                            "Low": 9000,
                            "Close": 10500,
                            "Volume": 100,
                            "Amount": 1000000,
                            "Time": "2026-05-06T09:35:00+08:00",
                        },
                        {
                            "Open": 12000,
                            "High": 13000,
                            "Low": 11000,
                            "Close": 12500,
                            "Volume": 200,
                            "Amount": 2000000,
                            "Time": "2026-05-07T09:35:00+08:00",
                        },
                    ],
                },
            }

        async def _fetch_adjust_factors(self, symbol, start_date, end_date):
            assert symbol == "000001.XSHE"
            assert start_date == date(2026, 5, 6)
            assert end_date == date(2026, 5, 7)
            return [(date(2026, 5, 6), 0.8), (date(2026, 5, 7), 0.9)]

    source = FakeTdxSource(SourceConfig(name="tdx", enabled=True, priority=110))
    result = await source.fetch_price(
        PriceQuery(symbol="000001.XSHE", market="cn", interval="5m", adjusted=True)
    )

    assert result[0]["open"] == 8
    assert result[0]["high"] == 8.8
    assert result[0]["low"] == 7.2
    assert result[0]["close"] == 8.4
    assert result[0]["volume"] == 10000
    assert result[1]["open"] == 10.8
    assert result[1]["close"] == 11.25


def test_tdx_search_keyword_only_handles_a_share_queries():
    assert _to_tdx_search_keyword("平安", False) == "平安"
    assert _to_tdx_search_keyword("000001.SH", True) == "000001"
    assert _to_tdx_search_keyword("0700", True) is None
    assert _to_tdx_search_keyword("0700.HK", True) is None
    assert _to_tdx_search_keyword("AAPL", False) is None


async def test_tdx_search_normalizes_symbols_and_filters_symbol_query():
    class FakeTdxSource(TdxSource):
        async def _get(self, path, params=None):
            assert path == "/api/search"
            assert params == {"keyword": "000001"}
            return {
                "code": 0,
                "message": "success",
                "data": [
                    {"code": "000001", "exchange": "sz", "name": "平安银行"},
                    {"code": "600001", "exchange": "sh", "name": "邯郸钢铁"},
                ],
            }

    source = FakeTdxSource(SourceConfig(name="tdx", enabled=True, priority=110))
    result = await source.fetch_equity_search("000001.SH", is_symbol=True)

    assert result == []


async def test_tdx_search_returns_matching_a_share_suffix_symbol():
    class FakeTdxSource(TdxSource):
        async def _get(self, path, params=None):
            assert path == "/api/search"
            assert params == {"keyword": "000001"}
            return {
                "code": 0,
                "message": "success",
                "data": [{"code": "000001", "exchange": "sz", "name": "平安银行"}],
            }

    source = FakeTdxSource(SourceConfig(name="tdx", enabled=True, priority=110))
    result = await source.fetch_equity_search("000001.SZ", is_symbol=True)

    assert result == [{"symbol": "000001.XSHE", "name": "平安银行", "source": "tdx"}]
