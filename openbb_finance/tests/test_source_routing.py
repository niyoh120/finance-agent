import pytest
from openbb_finance.models.equity_search import FinanceEquitySearchFetcher
from openbb_finance.models.index_snapshots import FinanceIndexSnapshotsFetcher

pytestmark = pytest.mark.anyio


class FakeSource:
    def __init__(self, name):
        self.name = name
        self.enabled = True

    async def fetch_equity_search(self, query, is_symbol=None):
        if self.name == "tickflow":
            return [{"symbol": "600519.XSHG", "name": "贵州茅台", "source": self.name}]
        raise RuntimeError("source unavailable")

    async def fetch_index_snapshots(self, region, symbols=None):
        return [{"symbol": "000001.XSHG", "name": "上证指数", "source": self.name}]


async def test_equity_search_routes_tdx_before_tickflow():
    class FakeRegistry:
        def ordered_by_names(self, names):
            assert names == ["tdx", "tickflow", "eastmoney", "akshare"]
            return [FakeSource(name) for name in names]

    query = FinanceEquitySearchFetcher.transform_query({"query": "茅台"})
    result = await FinanceEquitySearchFetcher.aextract_data(query, credentials=None, registry=FakeRegistry())

    assert result == [{"symbol": "600519.XSHG", "name": "贵州茅台", "source": "tickflow"}]


async def test_index_snapshots_only_uses_tickflow():
    class FakeRegistry:
        def ordered_by_names(self, names):
            assert names == ["tickflow"]
            return [FakeSource(name) for name in names]

    query = FinanceIndexSnapshotsFetcher.transform_query({"region": "cn"})
    result = await FinanceIndexSnapshotsFetcher.aextract_data(query, credentials=None, registry=FakeRegistry())

    assert result == [{"symbol": "000001.XSHG", "name": "上证指数", "source": "tickflow"}]
