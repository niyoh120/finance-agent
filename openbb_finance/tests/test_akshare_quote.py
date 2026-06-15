import sys
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest
from openbb_finance.config import SourceConfig
from openbb_finance.models.equity_quote import FinanceEquityQuoteFetcher
from openbb_finance.sources.akshare import AkshareSource
from openbb_finance.sources.base import PriceQuery
from openbb_finance.sources.yahoo import YahooSource


@pytest.mark.anyio
async def test_akshare_quote_falls_back_to_individual_info(monkeypatch):
    def stock_zh_a_spot_em():
        raise ConnectionError("spot endpoint unavailable")

    def stock_individual_info_em(symbol):
        assert symbol == "600000"
        return pd.DataFrame(
            [
                {"item": "股票代码", "value": "600000"},
                {"item": "股票简称", "value": "浦发银行"},
                {"item": "最新", "value": "9.37"},
            ]
        )

    akshare = SimpleNamespace(
        stock_zh_a_spot_em=stock_zh_a_spot_em,
        stock_individual_info_em=stock_individual_info_em,
    )
    monkeypatch.setitem(sys.modules, "akshare", akshare)

    source = AkshareSource(SourceConfig(name="akshare", enabled=True, priority=70))
    result = await source.fetch_quote("600000.SH")

    assert result["symbol"] == "600000.XSHG"
    assert result["name"] == "浦发银行"
    assert result["last_price"] == 9.37
    assert result["source"] == "akshare"


@pytest.mark.anyio
async def test_akshare_search_matches_a_share_suffix_symbol(monkeypatch):
    def stock_info_a_code_name():
        return pd.DataFrame([{"code": "600000", "name": "浦发银行"}])

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(stock_info_a_code_name=stock_info_a_code_name))

    source = AkshareSource(SourceConfig(name="akshare", enabled=True, priority=70))
    result = await source.fetch_equity_search("600000.SH", is_symbol=True)

    assert result == [{"symbol": "600000.XSHG", "name": "浦发银行", "source": "akshare"}]


@pytest.mark.anyio
async def test_akshare_adjusted_intraday_uses_qfq(monkeypatch):
    captured = {}

    def stock_zh_a_hist_min_em(symbol, period, adjust):
        captured.update({"symbol": symbol, "period": period, "adjust": adjust})
        return pd.DataFrame(
            [
                {
                    "时间": "2026-05-08 09:35:00",
                    "开盘": 10.0,
                    "最高": 11.0,
                    "最低": 9.0,
                    "收盘": 10.5,
                    "成交量": 100,
                    "成交额": 1000.0,
                }
            ]
        )

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(stock_zh_a_hist_min_em=stock_zh_a_hist_min_em))

    source = AkshareSource(SourceConfig(name="akshare", enabled=True, priority=70))
    result = await source.fetch_price(
        PriceQuery(symbol="600000.XSHG", market="cn", interval="5m", adjusted=True)
    )

    assert captured == {"symbol": "600000", "period": "5", "adjust": "qfq"}
    assert result[0]["date"] == datetime(2026, 5, 8, 9, 35)
    assert result[0]["close"] == 10.5


@pytest.mark.anyio
async def test_equity_quote_cn_falls_back_to_akshare():
    class FakeSource:
        def __init__(self, name):
            self.name = name
            self.enabled = True

        async def fetch_quote(self, symbol):
            if self.name == "akshare":
                return {"symbol": symbol, "last_price": 9.37, "source": self.name}
            raise RuntimeError("source unavailable")

    class FakeRegistry:
        def ordered_by_names(self, names):
            assert names == ["tdx", "tickflow", "akshare"]
            return [FakeSource(name) for name in names]

    query = FinanceEquityQuoteFetcher.transform_query({"symbol": "600000.SH"})
    result = await FinanceEquityQuoteFetcher.aextract_data(query, credentials=None, registry=FakeRegistry())

    assert result == [{"symbol": "600000.SH", "last_price": 9.37, "source": "akshare"}]


@pytest.mark.anyio
async def test_equity_quote_us_routes_tdx_before_fallbacks():
    class FakeSource:
        def __init__(self, name):
            self.name = name
            self.enabled = True

        async def fetch_quote(self, symbol):
            return {"symbol": symbol, "last_price": 297.28, "source": self.name}

    class FakeRegistry:
        def ordered_by_names(self, names):
            assert names == ["tdx", "tickflow", "yahoo"]
            return [FakeSource(name) for name in names]

    query = FinanceEquityQuoteFetcher.transform_query({"symbol": "AAPL"})
    result = await FinanceEquityQuoteFetcher.aextract_data(query, credentials=None, registry=FakeRegistry())

    assert result == [{"symbol": "AAPL", "last_price": 297.28, "source": "tdx"}]


@pytest.mark.anyio
async def test_yahoo_quote_maps_china_symbol_for_yfinance(monkeypatch):
    captured = {}

    def quote(symbol, provider):
        captured["symbol"] = symbol
        captured["provider"] = provider
        quote_result = SimpleNamespace(model_dump=lambda: {"symbol": "600000.SS", "last_price": 9.37})
        return SimpleNamespace(results=[quote_result])

    obb = SimpleNamespace(equity=SimpleNamespace(price=SimpleNamespace(quote=quote)))
    monkeypatch.setitem(sys.modules, "openbb", SimpleNamespace(obb=obb))

    source = YahooSource(SourceConfig(name="yahoo", enabled=True, priority=60))
    result = await source.fetch_quote("600000.SH")

    assert captured == {"symbol": "600000.SS", "provider": "yfinance"}
    assert result["symbol"] == "600000.XSHG"
    assert result["last_price"] == 9.37
    assert result["source"] == "yahoo"
