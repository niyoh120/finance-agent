from datetime import date, datetime

import pandas as pd
import pytest
from easy_tdx import Adjust, ExMarket, Period
from openbb_finance.config import SourceConfig
from openbb_finance.sources import tdx as tdx_module
from openbb_finance.sources.base import PriceQuery, SourceError
from openbb_finance.sources.tdx import (
    TdxSource,
    _futures_contract_symbol,
    _to_cn_market_code,
    _to_ex_market_code,
    _to_futures_market_code,
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

    def goods_list(self, market, start=0, count=600):
        self.__class__.calls.append(("goods_list", market, start, count))
        all_rows = [
            {"category": 3, "market": 66, "code": "SIL8", "name": "工业硅主连", "desc": ""},
            {"category": 3, "market": 66, "code": "SIL7", "name": "工业硅次连", "desc": ""},
            {"category": 3, "market": 66, "code": "SIL9", "name": "工业硅加权", "desc": ""},
            {"category": 3, "market": 66, "code": "SI2608", "name": "工业硅2608", "desc": ""},
            {"category": 3, "market": 66, "code": "SI2609", "name": "工业硅2609", "desc": ""},
            {"category": 3, "market": 30, "code": "RBL8", "name": "螺纹主连", "desc": ""},
            {"category": 3, "market": 30, "code": "RB2610", "name": "螺纹2610", "desc": ""},
            {"category": 3, "market": 16, "code": "GC00W", "name": "COMEX黄金主连", "desc": ""},
            {"category": 3, "market": 16, "code": "GC00Y", "name": "COMEX黄金连续", "desc": ""},
            {"category": 11, "market": 46, "code": "Au(T+D)", "name": "Au(T+D)", "desc": ""},
        ]
        filtered = [row for row in all_rows if row["market"] == market]
        if not filtered:
            return pd.DataFrame(columns=["category", "market", "code", "name", "desc"])
        return pd.DataFrame(filtered)


@pytest.fixture(autouse=True)
def reset_fake_clients(monkeypatch):
    FakeMacClient.calls = []
    FakeMacExClient.calls = []
    monkeypatch.setattr(tdx_module, "MacClient", FakeMacClient)
    monkeypatch.setattr(tdx_module, "MacExClient", FakeMacExClient)


def make_source() -> TdxSource:
    return TdxSource(SourceConfig(name="tdx", enabled=True))


def test_tdx_symbol_mapping():
    assert _to_tdx_code("600519.XSHG") == "600519"
    assert _to_tdx_code("000001.SZ") == "000001"
    assert _to_cn_market_code("600519.XSHG") == (1, "600519")
    assert _to_cn_market_code("000001.XSHE") == (0, "000001")
    assert _to_ex_market_code("700.HK", "hk") == (ExMarket.HK_MAIN_BOARD, "00700")
    assert _to_ex_market_code("8001.HK", "hk") == (ExMarket.HK_GEM, "08001")
    assert _to_ex_market_code("AAPL", "us") == (ExMarket.US_STOCK, "AAPL")
    assert _to_ex_market_code("SPX", "us") == (ExMarket.INTL_INDEX, "A_SPX")
    assert _to_ex_market_code("HSI", "hk") == (ExMarket.HK_INDEX, "HSI")
    assert _to_ex_market_code("HSCEI", "hk") == (ExMarket.HK_INDEX, "HZ5014")
    assert _to_ex_market_code("HSTECH", "hk") == (ExMarket.HK_INDEX, "HZ5017")
    with pytest.raises(SourceError):
        _to_tdx_code("AAPL")


def test_futures_market_code_translation_domestic():
    assert _to_futures_market_code("rb.SHFE") == (ExMarket.SH_FUTURES, "RBL8")
    assert _to_futures_market_code("rb.SHFE", "2026-10") == (ExMarket.SH_FUTURES, "RB2610")
    assert _to_futures_market_code("IF.CFFEX", "2026-12") == (ExMarket.CFFEX_FUTURES, "IF2612")
    assert _to_futures_market_code("si.GFEX", "2026-08") == (ExMarket.GZ_FUTURES, "SI2608")
    assert _to_futures_market_code("M.DCE") == (ExMarket.DL_FUTURES, "ML8")
    assert _to_futures_market_code("SR.CZCE") == (ExMarket.ZZ_FUTURES, "SRL8")


def test_futures_market_code_translation_international_month_letter():
    assert _to_futures_market_code("GC.COMEX") == (ExMarket.COMEX_FUTURES, "GC00W")
    assert _to_futures_market_code("GC.COMEX", "2026-12") == (ExMarket.COMEX_FUTURES, "GC26Z")
    assert _to_futures_market_code("GC.COMEX", "2026-01") == (ExMarket.COMEX_FUTURES, "GC26F")
    assert _to_futures_market_code("CL.NYMEX") == (ExMarket.NYMEX_FUTURES, "CL00W")
    assert _to_futures_market_code("ZL.CBOT", "2026-07") == (ExMarket.CBOT_FUTURES, "ZL26N")


def test_futures_market_code_translation_sge_fixed_map():
    assert _to_futures_market_code("AU.SGE") == (ExMarket.SH_GOLD, "Au(T+D)")
    assert _to_futures_market_code("AG.SGE") == (ExMarket.SH_GOLD, "Ag(T+D)")
    assert _to_futures_market_code("AU9999.SGE") == (ExMarket.SH_GOLD, "Au99.99")
    # SGE ignores expiration (no month contracts).
    assert _to_futures_market_code("AU.SGE", "2026-12") == (ExMarket.SH_GOLD, "Au(T+D)")


def test_futures_market_code_rejects_unknown_sge_product():
    with pytest.raises(SourceError):
        _to_futures_market_code("XYZ.SGE")
    with pytest.raises(SourceError):
        _to_futures_market_code("RB.UNKNOWN")


def test_futures_contract_symbol_round_trips_tdx_codes():
    assert _futures_contract_symbol("SHFE", "RBL8") == ("RB.SHFE", None)
    assert _futures_contract_symbol("SHFE", "RB2610") == ("RB.SHFE", "2026-10")
    assert _futures_contract_symbol("GFEX", "SIL8") == ("SI.GFEX", None)
    assert _futures_contract_symbol("GFEX", "SI2608") == ("SI.GFEX", "2026-08")
    assert _futures_contract_symbol("COMEX", "GC00W") == ("GC.COMEX", None)
    assert _futures_contract_symbol("COMEX", "GC26Z") == ("GC.COMEX", "2026-12")
    assert _futures_contract_symbol("SGE", "Au(T+D)") == ("AU.SGE", None)
    assert _futures_contract_symbol("CFFEX", "IFL8") == ("IF.CFFEX", None)
    assert _futures_contract_symbol("CFFEX", "IF2612") == ("IF.CFFEX", "2026-12")


async def test_tdx_futures_price_uses_ex_client_and_main_continuous_code():
    result = await make_source().fetch_price(PriceQuery(symbol="rb.SHFE", market="future", interval="1d"))

    assert FakeMacExClient.calls[1] == (
        "goods_kline",
        ExMarket.SH_FUTURES,
        "RBL8",
        Period.DAILY,
        0,
        700,
        Adjust.NONE,
    )
    assert result[0]["symbol"] == "RB.SHFE"
    assert result[0]["source"] == "tdx"


async def test_tdx_futures_price_uses_month_contract_code_for_expiration():
    result = await make_source().fetch_price(
        PriceQuery(symbol="GC.COMEX", market="future", expiration="2026-12", interval="1d")
    )

    assert FakeMacExClient.calls[1] == (
        "goods_kline",
        ExMarket.COMEX_FUTURES,
        "GC26Z",
        Period.DAILY,
        0,
        700,
        Adjust.NONE,
    )
    assert result[0]["symbol"] == "GC.COMEX"


async def test_tdx_futures_quote_includes_name():
    result = await make_source().fetch_quote("AU.SGE")

    assert FakeMacExClient.calls[1] == ("goods_quotes", [(ExMarket.SH_GOLD, "Au(T+D)")])
    assert result["symbol"] == "AU.SGE"
    assert result["name"] == "苹果"
    assert result["last_price"] == 297.28
    assert result["source"] == "tdx"


async def test_tdx_futures_search_matches_symbol_and_name():
    by_symbol = await make_source().fetch_futures_search("si", is_symbol=True)
    si_codes = [row["code"] for row in by_symbol if row["exchange"] == "GFEX"]
    assert si_codes == ["SIL8", "SI2608", "SI2609"]
    assert by_symbol[0]["symbol"] == "SI.GFEX"
    assert by_symbol[0]["expiration"] is None

    by_name = await make_source().fetch_futures_search("螺纹", is_symbol=False)
    assert {row["code"] for row in by_name} == {"RBL8", "RB2610"}
    assert {row["exchange"] for row in by_name} == {"SHFE"}


async def test_tdx_futures_search_filters_auxiliary_continuous_codes():
    results = await make_source().fetch_futures_search("SI", is_symbol=True)
    gfex_codes = [row["code"] for row in results if row["exchange"] == "GFEX"]
    # 次连 (L7) / 加权 (L9) are not queryable via symbol+expiration and are filtered.
    assert gfex_codes == ["SIL8", "SI2608", "SI2609"]
    assert results[0]["symbol"] == "SI.GFEX"

    comex = await make_source().fetch_futures_search("GC", is_symbol=True)
    comex_codes = [row["code"] for row in comex if row["exchange"] == "COMEX"]
    # 连续 (00Y) filtered, 主连 (00W) kept.
    assert comex_codes == ["GC00W"]


async def test_tdx_futures_search_includes_sge_fixed_products():
    results = await make_source().fetch_futures_search("AU", is_symbol=True)
    sge_rows = [row for row in results if row["exchange"] == "SGE"]
    assert sge_rows == [
        {
            "symbol": "AU.SGE",
            "expiration": None,
            "code": "Au(T+D)",
            "name": "Au(T+D)",
            "exchange": "SGE",
            "source": "tdx",
        }
    ]


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
    result = await make_source().fetch_price(PriceQuery(symbol="700.HK", market="hk", interval="1m", adjusted=False))

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


async def test_tdx_us_index_price_uses_intl_index_market():
    result = await make_source().fetch_price(PriceQuery(symbol="SPX", market="us", interval="1d"))

    assert FakeMacExClient.calls[1] == (
        "goods_kline",
        ExMarket.INTL_INDEX,
        "A_SPX",
        Period.DAILY,
        0,
        700,
        Adjust.NONE,
    )
    assert result[0]["symbol"] == "SPX"
    assert result[0]["source"] == "tdx"


async def test_tdx_hk_index_price_uses_hk_index_market():
    await make_source().fetch_price(PriceQuery(symbol="HSTECH", market="hk", interval="1d"))

    assert FakeMacExClient.calls[1] == (
        "goods_kline",
        ExMarket.HK_INDEX,
        "HZ5017",
        Period.DAILY,
        0,
        700,
        Adjust.NONE,
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
