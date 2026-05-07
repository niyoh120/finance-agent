"""Tests for index models."""

from __future__ import annotations

import pytest
from openbb_finance.config import SourceConfig
from openbb_finance.models.index_available import FinanceAvailableIndicesFetcher
from openbb_finance.sources.eastmoney import EastmoneySource
from openbb_finance.sources.sina import SinaSource, _parse_hk


@pytest.fixture
def eastmoney_source() -> EastmoneySource:
    config = SourceConfig(name="eastmoney", enabled=True, priority=95)
    return EastmoneySource(config)


@pytest.fixture
def sina_source() -> SinaSource:
    config = SourceConfig(name="sina", enabled=True, priority=98)
    return SinaSource(config)


@pytest.mark.anyio
async def test_index_search_cn_index(eastmoney_source: EastmoneySource):
    """Test searching Chinese index."""
    results = await eastmoney_source.fetch_index_search("上证")
    assert len(results) > 0
    assert any("000001" in r["symbol"] for r in results)
    sh_index = next(r for r in results if "000001" in r["symbol"])
    assert "上证" in sh_index["name"] or "指数" in sh_index["name"]


@pytest.mark.anyio
async def test_index_search_us_index(eastmoney_source: EastmoneySource):
    """Test searching US index."""
    results = await eastmoney_source.fetch_index_search("SPX")
    assert len(results) > 0
    assert any(r["symbol"] == "SPX" for r in results)


@pytest.mark.anyio
async def test_index_search_hk_index(eastmoney_source: EastmoneySource):
    """Test searching HK index."""
    results = await eastmoney_source.fetch_index_search("恒生")
    assert len(results) > 0
    assert any(r["symbol"] == "HSI" for r in results)


@pytest.mark.anyio
async def test_index_search_is_symbol(eastmoney_source: EastmoneySource):
    """Test index search with is_symbol=True."""
    results = await eastmoney_source.fetch_index_search("000001", is_symbol=True)
    assert len(results) > 0
    # Should match symbol 000001
    assert any("000001" in r["symbol"] for r in results)


@pytest.mark.anyio
async def test_index_snapshots_cn(sina_source: SinaSource):
    """Test fetching CN index snapshots."""
    results = await sina_source.fetch_index_snapshots(region="cn")
    assert len(results) > 0
    symbols = [r["symbol"] for r in results]
    assert any(s in symbols for s in ["000001.XSHG", "000300.XSHG", "000905.XSHG"])
    first = results[0]
    assert "symbol" in first
    assert "name" in first
    assert "price" in first


@pytest.mark.anyio
async def test_index_snapshots_us(sina_source: SinaSource):
    """Test fetching US index snapshots."""
    results = await sina_source.fetch_index_snapshots(region="us")
    assert len(results) > 0
    symbols = [r["symbol"] for r in results]
    assert any(s in symbols for s in ["SPX", "DJI", "NDX"])


@pytest.mark.anyio
async def test_index_snapshots_hk(sina_source: SinaSource):
    """Test fetching HK index snapshots."""
    results = await sina_source.fetch_index_snapshots(region="hk")
    assert len(results) > 0
    symbols = [r["symbol"] for r in results]
    assert "HSI" in symbols


@pytest.mark.anyio
async def test_index_snapshots_with_symbols(sina_source: SinaSource):
    """Test fetching index snapshots with specific symbols."""
    results = await sina_source.fetch_index_snapshots(
        region="cn",
        symbols=["000001", "000300"],
    )
    assert len(results) >= 2
    symbols = [r["symbol"] for r in results]
    assert "000001.XSHG" in symbols
    assert "000300.XSHG" in symbols


def test_sina_hk_index_snapshot_field_mapping():
    fields = (
        "HSI,恒生指数,26008.320,26111.840,26072.240,25734.160,25776.529,"
        "-335.310,-1.280,0.000,0.000,291552653.621,16811064518"
    ).split(",")

    result = _parse_hk("HSI", fields)

    assert result is not None
    assert result["open"] == 26008.32
    assert result["prev_close"] == 26111.84
    assert result["high"] == 26072.24
    assert result["low"] == 25734.16
    assert result["price"] == 25776.529
    assert result["close"] == 25776.529


@pytest.mark.anyio
async def test_available_indices_returns_supported_symbols():
    query = FinanceAvailableIndicesFetcher.transform_query({})
    results = await FinanceAvailableIndicesFetcher.aextract_data(
        query,
        credentials=None,
    )
    data = FinanceAvailableIndicesFetcher.transform_data(query, results)

    symbols = [item.symbol for item in data]
    assert "000001.XSHG" in symbols
    assert "000300.XSHG" in symbols
    assert "000852.XSHG" in symbols
    assert "SPX" in symbols
    assert "NDX" in symbols
    assert "HSI" in symbols
    assert "HSTECH" in symbols
    assert {item.source for item in data} == {"tickflow"}


@pytest.mark.anyio
async def test_available_indices_merges_tickflow_universe_api_with_static_indices():
    query = FinanceAvailableIndicesFetcher.transform_query({})
    results = await FinanceAvailableIndicesFetcher.aextract_data(
        query,
        credentials=None,
        registry=_FakeIndexRegistry(),
    )

    symbols = [item["symbol"] for item in results]
    assert symbols.count("NDX") == 1
    assert "000001.XSHG" in symbols
    assert "SPX" in symbols
    assert "HSI" in symbols
    assert "HSTECH" in symbols


class _FakeIndexRegistry:
    def ordered_by_names(self, names):
        assert names == ["tickflow"]
        return [_FakeTickflowIndexSource()]


class _FakeTickflowIndexSource:
    async def fetch_available_indices(self):
        return [
            {
                "symbol": "NDX",
                "name": "NASDAQ 100",
                "exchange": "US",
                "currency": "USD",
                "source": "tickflow",
            }
        ]
