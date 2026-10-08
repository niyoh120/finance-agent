import pytest
from openbb_finance.models.company_news import FinanceCompanyNewsFetcher
from openbb_finance.models.equity_quote import FinanceEquityQuoteFetcher
from openbb_finance.models.equity_search import FinanceEquitySearchFetcher
from openbb_finance.models.index_snapshots import FinanceIndexSnapshotsFetcher
from openbb_finance.models.world_news import FinanceWorldNewsFetcher

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

    async def fetch_news(self, query, limit=None):
        return [{"date": "2026-06-28", "title": "News", "source": self.name}]

    async def fetch_world_news(self, limit=None, start_date=None, end_date=None):
        return [{"date": "2026-06-28", "title": "World", "source": self.name}]


async def test_equity_search_routes_tdx_before_tickflow():
    class FakeRegistry:
        def ordered_by_names(self, names):
            assert names == ["schwab", "tdx", "tickflow", "eastmoney", "akshare"]
            return [FakeSource(name) for name in names[1:]]  # schwab unregistered in this fixture

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


async def test_us_company_news_routes_finnhub_first():
    class FakeRegistry:
        def ordered_by_names(self, names):
            assert names == ["finnhub", "futunn", "openbb"]
            return [FakeSource(name) for name in names]

    query = FinanceCompanyNewsFetcher.transform_query({"symbol": "AAPL", "limit": 5})
    result = await FinanceCompanyNewsFetcher.aextract_data(query, credentials=None, registry=FakeRegistry())

    assert result[0]["source"] == "finnhub"


async def test_world_news_routes_finnhub_first():
    class FakeRegistry:
        def ordered_by_names(self, names):
            assert names == ["finnhub", "futunn", "openbb"]
            return [FakeSource(name) for name in names]

    query = FinanceWorldNewsFetcher.transform_query({"limit": 5})
    result = await FinanceWorldNewsFetcher.aextract_data(query, credentials=None, registry=FakeRegistry())

    assert result[0]["source"] == "finnhub"


# --------------------------------------------------------------------------- #
# equity.quote 空报价回退：仅标识字段的记录视为源失败，继续下一源
# --------------------------------------------------------------------------- #


def _quote_source(name: str, record: dict) -> object:
    class _QuoteSource:
        def __init__(self, source_name: str):
            self.name = source_name
            self.enabled = True

        async def fetch_quote(self, symbol: str) -> dict:
            return record

    return _QuoteSource(name)


async def test_equity_quote_skips_identifier_only_record_and_falls_back():
    """tdx 返回仅 symbol+source 的空快照时，回退到下一源而非短路。"""

    class FakeRegistry:
        def ordered_by_names(self, names):
            assert names == ["schwab", "tdx", "tickflow"]
            return [
                _quote_source("schwab", {"symbol": "ON", "source": "schwab"}),  # 同样空 → 也跳过
                _quote_source("tdx", {"symbol": "ON", "source": "tdx"}),  # 空快照 → 跳过
                _quote_source("tickflow", {"symbol": "ON", "last_price": 62.1, "source": "tickflow"}),
            ]

    query = FinanceEquityQuoteFetcher.transform_query({"symbol": "ON"})
    result = await FinanceEquityQuoteFetcher.aextract_data(query, credentials=None, registry=FakeRegistry())

    assert result == [{"symbol": "ON", "last_price": 62.1, "source": "tickflow"}]


async def test_equity_quote_accepts_first_source_with_market_data():
    class FakeRegistry:
        def ordered_by_names(self, names):
            return [
                _quote_source(
                    "schwab",
                    {"symbol": "ON", "last_price": 62.0, "bid": 61.9, "ask": 62.1, "source": "schwab"},
                ),
                _quote_source("tdx", {"symbol": "ON", "last_price": 61.5, "source": "tdx"}),
            ]

    query = FinanceEquityQuoteFetcher.transform_query({"symbol": "ON"})
    result = await FinanceEquityQuoteFetcher.aextract_data(query, credentials=None, registry=FakeRegistry())

    assert result[0]["source"] == "schwab"


async def test_equity_quote_all_sources_empty_returns_no_data():
    class FakeRegistry:
        def ordered_by_names(self, names):
            return [_quote_source(name, {"symbol": "ON", "source": name}) for name in names]

    query = FinanceEquityQuoteFetcher.transform_query({"symbol": "ON"})
    result = await FinanceEquityQuoteFetcher.aextract_data(query, credentials=None, registry=FakeRegistry())

    assert result == []
