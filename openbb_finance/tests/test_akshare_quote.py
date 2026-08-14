import sys
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest
from openbb_finance.config import SourceConfig
from openbb_finance.models.equity_quote import FinanceEquityQuoteFetcher
from openbb_finance.sources.akshare import AkshareSource
from openbb_finance.sources.base import PriceQuery


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

    source = AkshareSource(SourceConfig(name="akshare", enabled=True))
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

    source = AkshareSource(SourceConfig(name="akshare", enabled=True))
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

    source = AkshareSource(SourceConfig(name="akshare", enabled=True))
    result = await source.fetch_price(PriceQuery(symbol="600000.XSHG", market="cn", interval="5m", adjusted=True))

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
            assert names == ["tdx", "tickflow"]
            return [FakeSource(name) for name in names]

    query = FinanceEquityQuoteFetcher.transform_query({"symbol": "AAPL"})
    result = await FinanceEquityQuoteFetcher.aextract_data(query, credentials=None, registry=FakeRegistry())

    assert result == [{"symbol": "AAPL", "last_price": 297.28, "source": "tdx"}]


def _akshare_fake(**methods):
    return SimpleNamespace(**methods)


@pytest.mark.anyio
async def test_akshare_futures_price_uses_sina_main_continuous_code(monkeypatch):
    def futures_zh_daily_sina(symbol):
        assert symbol == "IF0"
        return pd.DataFrame(
            [
                {
                    "date": "2026-08-06",
                    "open": 4585.2,
                    "high": 4626.0,
                    "low": 4570.8,
                    "close": 4612.0,
                    "volume": 64989,
                    "hold": 146571,
                    "settle": 0.0,
                },
                {
                    "date": "2026-08-07",
                    "open": 4620.0,
                    "high": 4656.2,
                    "low": 4604.6,
                    "close": 4645.6,
                    "volume": 65609,
                    "hold": 151018,
                    "settle": 0.0,
                },
            ]
        )

    monkeypatch.setitem(sys.modules, "akshare", _akshare_fake(futures_zh_daily_sina=futures_zh_daily_sina))
    source = AkshareSource(SourceConfig(name="akshare", enabled=True))
    result = await source.fetch_futures_price(PriceQuery(symbol="IF.CFFEX", market="future"))

    assert result[-1]["symbol"] == "IF.CFFEX"
    assert result[-1]["date"].isoformat() == "2026-08-07"
    assert result[-1]["close"] == 4645.6
    assert result[-1]["volume"] == 65609.0
    assert result[-1]["source"] == "akshare"


@pytest.mark.anyio
async def test_akshare_futures_price_month_contract_code(monkeypatch):
    def futures_zh_daily_sina(symbol):
        assert symbol == "IF2609"
        return pd.DataFrame(
            [
                {
                    "date": "2026-08-07",
                    "open": 4620.0,
                    "high": 4656.2,
                    "low": 4604.6,
                    "close": 4645.6,
                    "volume": 65609,
                    "hold": 151018,
                    "settle": 0.0,
                },
            ]
        )

    monkeypatch.setitem(sys.modules, "akshare", _akshare_fake(futures_zh_daily_sina=futures_zh_daily_sina))
    source = AkshareSource(SourceConfig(name="akshare", enabled=True))
    result = await source.fetch_futures_price(PriceQuery(symbol="IF.CFFEX", market="future", expiration="2026-09"))

    assert result[0]["close"] == 4645.6


@pytest.mark.anyio
async def test_akshare_futures_price_rejects_sge(monkeypatch):
    from openbb_finance.sources.base import SourceError

    monkeypatch.setitem(sys.modules, "akshare", _akshare_fake())
    source = AkshareSource(SourceConfig(name="akshare", enabled=True))
    with pytest.raises(SourceError):
        await source.fetch_futures_price(PriceQuery(symbol="AU.SGE", market="future"))


@pytest.mark.anyio
async def test_akshare_futures_search_maps_symbol_to_chinese_product(monkeypatch):
    def futures_symbol_mark():
        return pd.DataFrame(
            [
                {"exchange": "广州期货交易所", "symbol": "工业硅", "mark": "si_qh"},
                {"exchange": "中国金融期货交易所", "symbol": "沪深300指数期货", "mark": "qz_qh"},
            ]
        )

    def futures_zh_realtime(symbol):
        if symbol == "工业硅":
            return pd.DataFrame(
                [
                    {"symbol": "SI0", "exchange": "gfex", "name": "工业硅连续", "trade": 8550.0},
                    {"symbol": "SI2609", "exchange": "gfex", "name": "工业硅2609", "trade": 8550.0},
                ]
            )
        return pd.DataFrame(
            [
                {"symbol": "IF0", "exchange": "cffex", "name": "沪深300指数期货连续", "trade": 4645.6},
                {"symbol": "IF2612", "exchange": "cffex", "name": "沪深300指数期货2612", "trade": 4565.6},
            ]
        )

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        _akshare_fake(futures_symbol_mark=futures_symbol_mark, futures_zh_realtime=futures_zh_realtime),
    )
    source = AkshareSource(SourceConfig(name="akshare", enabled=True))

    by_symbol = await source.fetch_futures_search("si", is_symbol=True)
    assert [row["code"] for row in by_symbol] == ["SI0", "SI2609"]
    assert by_symbol[0]["symbol"] == "SI.GFEX"
    assert by_symbol[0]["expiration"] is None
    assert by_symbol[1]["expiration"] == "2026-09"
    assert by_symbol[1]["exchange"] == "GFEX"
    assert by_symbol[1]["source"] == "akshare"

    by_name = await source.fetch_futures_search("沪深300", is_symbol=False)
    assert [row["code"] for row in by_name] == ["IF0", "IF2612"]
    assert by_name[1]["expiration"] == "2026-12"


@pytest.mark.anyio
async def test_akshare_futures_search_dotted_symbol_suffix(monkeypatch):
    def futures_symbol_mark():
        return pd.DataFrame(
            [
                {"exchange": "广州期货交易所", "symbol": "工业硅", "mark": "si_qh"},
            ]
        )

    def futures_zh_realtime(symbol):
        return pd.DataFrame(
            [
                {"symbol": "SI0", "exchange": "gfex", "name": "工业硅连续", "trade": 8550.0},
            ]
        )

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        _akshare_fake(futures_symbol_mark=futures_symbol_mark, futures_zh_realtime=futures_zh_realtime),
    )
    source = AkshareSource(SourceConfig(name="akshare", enabled=True))

    results = await source.fetch_futures_search("si.GFEX", is_symbol=True)
    assert [row["code"] for row in results] == ["SI0"]
