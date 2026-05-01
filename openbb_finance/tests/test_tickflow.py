import pytest

from openbb_finance.config import SourceConfig
from openbb_finance.sources.tickflow import TickflowSource, _to_tickflow_symbol

pytestmark = pytest.mark.anyio


def test_tickflow_symbol_mapping():
    assert _to_tickflow_symbol("600519.XSHG") == "600519.SH"
    assert _to_tickflow_symbol("159915.XSHE") == "159915.SZ"
    assert _to_tickflow_symbol("0700.HK") == "00700.HK"
    assert _to_tickflow_symbol("AAPL") == "AAPL.US"


async def test_tickflow_quote_uses_v1_quotes_payload():
    class FakeTickflowSource(TickflowSource):
        async def _fetch_quotes(self, symbols):
            assert symbols == ["600519.SH"]
            return [
                {
                    "symbol": "600519.SH",
                    "region": "CN",
                    "last_price": 1384.79,
                    "prev_close": 1401.17,
                    "open": 1400.0,
                    "high": 1401.17,
                    "low": 1380.0,
                    "volume": 52753,
                    "amount": 7316111700.0,
                    "timestamp": 1777532401000,
                    "ext": {
                        "name": "贵州茅台",
                        "change_pct": -0.0116902303,
                        "change_amount": -16.38,
                    },
                }
            ]

    source = FakeTickflowSource(SourceConfig(name="tickflow", enabled=True, priority=80, api_key="token"))
    result = await source.fetch_quote("600519.XSHG")

    assert result["symbol"] == "600519.XSHG"
    assert result["name"] == "贵州茅台"
    assert result["last_price"] == 1384.79
    assert result["change_percent"] == -1.16902303


async def test_tickflow_index_snapshots_outputs_openbb_symbols():
    class FakeTickflowSource(TickflowSource):
        async def _fetch_quotes(self, symbols):
            assert symbols[:2] == ["000001.SH", "000016.SH"]
            return [
                {
                    "symbol": "000001.SH",
                    "region": "CN",
                    "last_price": 4112.159,
                    "prev_close": 4107.514,
                    "open": 4107.297,
                    "high": 4118.755,
                    "low": 4100.966,
                    "volume": 656912728,
                    "amount": 1276194739100.0,
                    "timestamp": 1777532409000,
                    "ext": {
                        "name": "上证指数",
                        "change_pct": 0.00113085,
                        "change_amount": 4.645,
                    },
                }
            ]

    source = FakeTickflowSource(SourceConfig(name="tickflow", enabled=True, priority=80, api_key="token"))
    result = await source.fetch_index_snapshots(region="cn")

    assert result[0]["symbol"] == "000001.XSHG"
    assert result[0]["name"] == "上证指数"
    assert result[0]["currency"] == "CNY"
    assert result[0]["price"] == 4112.159
