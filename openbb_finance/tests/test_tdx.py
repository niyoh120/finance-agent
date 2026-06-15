from datetime import date, datetime

import pandas as pd
import pytest
from easy_tdx import Adjust, ExMarket, Period

from openbb_finance.config import SourceConfig
from openbb_finance.sources import tdx as tdx_module
from openbb_finance.sources.base import PriceQuery, SourceError
from openbb_finance.sources.tdx import (
    TdxSource,
    _to_cn_market_code,
    _to_ex_market_code,
    _to_tdx_code,
    _to_tdx_period,
)

pytestmark = pytest.mark.anyio


class FakeContext:
    def __init__(self, client):
        self.client = client

    def __enter__(self):
        return self.client

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeMacClient:
    calls = []

    @classmethod
    def from_best_host(cls, **kwargs):
        cls.calls.append(("from_best_host", kwargs))
        return FakeContext(cls())

    def get_stock_kline(self, market, code, period, start, count, times=1, adjust=Adjust.NONE):
        self.__class__.calls.append(("get_stock_kline", market, code, period, start, count, times, adjust))
        return pd.DataFrame(
            [
                {
                    "datetime": datetime(2026, 6, 13, 15, 0),
                    "open": 1250.0,
                    "high": 1260.0,
                    "low": 1240.0,
                    "close": 1255.0,
                    "vol": 1000,
                    "amount": 1_255_000.0,
                },
                {
                    "datetime": datetime(2026, 6, 15, 15, 0),
                    "open": 1292.7,
                    "high": 1292.7,
                    "low": 1270.1,
                    "close": 1271.1,
                    "vol": 41585,
                    "amount": 5_303_655_936.0,
                },
            ]
        )

    def get_stock_quotes(self, stocks):
        self.__class__.calls.append(("get_stock_quotes", stocks))
        return pd.DataFrame(
            [
                {
                    "market": 1,
                    "code": "600519",
                    "name": "贵州茅台",
                    "pre_close": 1291.91,
                    "open": 1292.7,
                    "high": 1292.7,
                    "low": 1270.1,
                    "close": 1271.1,
                    "vol": 41585,
                }
            ]
        )

    def get_symbol_info(self, market, code):
        self.__class__.calls.append(("get_symbol_info", market, code))
        return pd.DataFrame([{"market": market, "code": code, "name": "贵州茅台"}])


class FakeMacExClient:
    calls = []

    @classmethod
    def from_best_host(cls, **kwargs):
        cls.calls.append(("from_best_host", kwargs))
        return FakeContext(cls())

    def goods_kline(self, market, code, period, start, count, adjust=Adjust.NONE):
        self.__class__.calls.append(("goods_kline", market, code, period, start, count, adjust))
        return pd.DataFrame(
            [
                {
                    "datetime": datetime(2026, 6, 15, 21, 31),
                    "open": 294.12,
                    "high": 297.78,
                    "low": 291.70,
                    "close": 297.05,
                    "vol": 100,
                    "amount": 29_705.0,
                },
            ]
        )

    def goods_quotes(self, stocks):
        self.__class__.calls.append(("goods_quotes", stocks))
        return pd.DataFrame(
            [
                {
                    "market": 74,
                    "code": "AAPL",
                    "name": "苹果",
                    "pre_close": 291.13,
                    "open": 294.12,
                    "high": 297.78,
                    "low": 291.70,
                    "close": 297.28,
                    "vol": 17_429_069,
                }
            ]
        )


@pytest.fixture(autouse=True)
def reset_fake_clients(monkeypatch):
    FakeMacClient.calls = []
    FakeMacExClient.calls = []
    monkeypatch.setattr(tdx_module, "MacClient", FakeMacClient)
    monkeypatch.setattr(tdx_module, "MacExClient", FakeMacExClient)


def make_source() -> TdxSource:
    return TdxSource(SourceConfig(name="tdx", enabled=True, priority=110))


def test_tdx_symbol_mapping():
    assert _to_tdx_code("600519.XSHG") == "600519"
    assert _to_tdx_code("000001.SZ") == "000001"
    assert _to_cn_market_code("600519.XSHG") == (1, "600519")
    assert _to_cn_market_code("000001.XSHE") == (0, "000001")
    assert _to_ex_market_code("700.HK", "hk") == (ExMarket.HK_MAIN_BOARD, "00700")
    assert _to_ex_market_code("8001.HK", "hk") == (ExMarket.HK_GEM, "08001")
    assert _to_ex_market_code("AAPL", "us") == (ExMarket.US_STOCK, "AAPL")
    with pytest.raises(SourceError):
        _to_tdx_code("AAPL")


def test_tdx_period_mapping():
    assert _to_tdx_period("1") == Period.MIN_1
    assert _to_tdx_period("5m") == Period.MIN_5
    assert _to_tdx_period("60") == Period.MIN_60
    assert _to_tdx_period("1d") == Period.DAILY
    assert _to_tdx_period("1w") == Period.WEEKLY
    assert _to_tdx_period("1M") == Period.MONTHLY


async def test_tdx_cn_price_uses_mac_client_and_native_adjust():
    result = await make_source().fetch_price(
        PriceQuery(
            symbol="600519.XSHG",
            market="cn",
            start_date=date(2026, 6, 15),
            end_date=date(2026, 6, 15),
            interval="1d",
            adjusted=True,
        )
    )

    assert FakeMacClient.calls[0] == ("from_best_host", {"timeout": 15.0})
    assert FakeMacClient.calls[1] == ("get_stock_kline", 1, "600519", Period.DAILY, 0, 700, 1, Adjust.QFQ)
    assert result == [
        {
            "symbol": "600519.XSHG",
            "date": date(2026, 6, 15),
            "open": 1292.7,
            "high": 1292.7,
            "low": 1270.1,
            "close": 1271.1,
            "volume": 41585.0,
            "amount": 5303655936.0,
            "source": "tdx",
        }
    ]


async def test_tdx_hk_price_zero_pads_code_and_preserves_intraday_datetime():
    result = await make_source().fetch_price(
        PriceQuery(symbol="700.HK", market="hk", interval="1m", adjusted=False)
    )

    assert FakeMacExClient.calls[1] == (
        "goods_kline",
        ExMarket.HK_MAIN_BOARD,
        "00700",
        Period.MIN_1,
        0,
        700,
        Adjust.NONE,
    )
    assert result[0]["symbol"] == "700.HK"
    assert result[0]["date"] == datetime(2026, 6, 15, 21, 31)
    assert result[0]["close"] == 297.05
    assert result[0]["volume"] == 10000.0


async def test_tdx_us_price_uses_us_stock_market():
    await make_source().fetch_price(PriceQuery(symbol="AAPL", market="us", interval="5m", adjusted=True))

    assert FakeMacExClient.calls[1] == (
        "goods_kline",
        ExMarket.US_STOCK,
        "AAPL",
        Period.MIN_5,
        0,
        700,
        Adjust.QFQ,
    )


async def test_tdx_cn_quote_normalizes_mac_client_payload():
    result = await make_source().fetch_quote("600519.XSHG")

    assert FakeMacClient.calls[1] == ("get_stock_quotes", [(1, "600519")])
    assert result["symbol"] == "600519.XSHG"
    assert result["last_price"] == 1271.1
    assert result["prev_close"] == 1291.91
    assert result["volume"] == 4158500.0
    assert result["change"] == pytest.approx(-20.81)
    assert result["change_percent"] == pytest.approx(-1.6107925466959658)
    assert result["source"] == "tdx"


async def test_tdx_us_quote_uses_mac_ex_client_payload():
    result = await make_source().fetch_quote("AAPL")

    assert FakeMacExClient.calls[1] == ("goods_quotes", [(ExMarket.US_STOCK, "AAPL")])
    assert result["symbol"] == "AAPL"
    assert result["last_price"] == 297.28
    assert result["volume"] == 17429069.0
    assert result["source"] == "tdx"


async def test_tdx_exact_symbol_search_uses_mac_client_metadata():
    result = await make_source().fetch_equity_search("600519.XSHG", is_symbol=True)

    assert FakeMacClient.calls[1] == ("get_symbol_info", 1, "600519")
    assert result == [{"symbol": "600519.XSHG", "name": "贵州茅台", "source": "tdx"}]


async def test_tdx_keyword_search_falls_through_to_richer_sources():
    assert await make_source().fetch_equity_search("茅台", is_symbol=False) == []
