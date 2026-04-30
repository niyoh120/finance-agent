"""Tests for index models."""

from __future__ import annotations

import pytest
from openbb_finance.config import SourceConfig
from openbb_finance.sources.eastmoney import EastmoneySource


@pytest.fixture
def eastmoney_source() -> EastmoneySource:
    config = SourceConfig(name="eastmoney", enabled=True, priority=95)
    return EastmoneySource(config)


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
async def test_index_snapshots_cn(eastmoney_source: EastmoneySource):
    """Test fetching CN index snapshots."""
    results = await eastmoney_source.fetch_index_snapshots(region="cn")
    assert len(results) > 0
    # Should have default CN indices
    symbols = [r["symbol"] for r in results]
    assert any(s in symbols for s in ["000001", "000300", "000905"])
    # Check data structure
    first = results[0]
    assert "symbol" in first
    assert "name" in first
    assert "price" in first


@pytest.mark.anyio
async def test_index_snapshots_us(eastmoney_source: EastmoneySource):
    """Test fetching US index snapshots."""
    results = await eastmoney_source.fetch_index_snapshots(region="us")
    assert len(results) > 0
    symbols = [r["symbol"] for r in results]
    assert any(s in symbols for s in ["SPX", "DJI", "NDX"])


@pytest.mark.anyio
async def test_index_snapshots_hk(eastmoney_source: EastmoneySource):
    """Test fetching HK index snapshots."""
    results = await eastmoney_source.fetch_index_snapshots(region="hk")
    assert len(results) > 0
    symbols = [r["symbol"] for r in results]
    assert "HSI" in symbols


@pytest.mark.anyio
async def test_index_snapshots_with_symbols(eastmoney_source: EastmoneySource):
    """Test fetching index snapshots with specific symbols."""
    results = await eastmoney_source.fetch_index_snapshots(
        region="cn",
        symbols=["000001", "000300"],
    )
    assert len(results) >= 2
    symbols = [r["symbol"] for r in results]
    assert "000001" in symbols
    assert "000300" in symbols
