"""Tests for Eastmoney search source."""

from __future__ import annotations

import pytest
from openbb_finance.config import SourceConfig
from openbb_finance.sources.base import PriceQuery, SourceError
from openbb_finance.sources.eastmoney import EastmoneySource, normalize_hk_symbol


@pytest.fixture
def eastmoney_source() -> EastmoneySource:
    config = SourceConfig(name="eastmoney", enabled=True)
    return EastmoneySource(config)


def test_normalize_hk_symbol():
    """Test HK symbol normalization."""
    assert normalize_hk_symbol("00700") == "0700.HK"
    assert normalize_hk_symbol("09988") == "9988.HK"
    assert normalize_hk_symbol("00001") == "0001.HK"
    assert normalize_hk_symbol("01234") == "1234.HK"


def test_eastmoney_source_supports_search(eastmoney_source: EastmoneySource):
    """Test that EastmoneySource supports search data type."""
    assert eastmoney_source.supports("cn", "search")
    assert eastmoney_source.supports("us", "search")
    assert eastmoney_source.supports("hk", "search")
    # Eastmoney now supports price for A-share ETFs
    assert eastmoney_source.supports("cn", "price")
    assert not eastmoney_source.supports("us", "price")
    assert not eastmoney_source.supports("hk", "price")


def test_eastmoney_index_symbol_normalization(eastmoney_source: EastmoneySource):
    assert eastmoney_source._normalize_index_symbol("000001", "Index") == "000001.XSHG"
    assert eastmoney_source._normalize_index_symbol("399001", "Index") == "399001.XSHE"


def test_eastmoney_etf_detection_and_normalization(eastmoney_source: EastmoneySource):
    assert eastmoney_source._is_etf({"Classify": "Fund", "SecurityType": "8"})
    assert eastmoney_source._is_etf({"Classify": "UsStock", "SecurityType": "7", "TypeUS": "5"})
    assert eastmoney_source._is_etf({"Classify": "HK", "SecurityType": "6"})
    assert not eastmoney_source._is_etf({"Classify": "UsStock", "SecurityType": "7", "TypeUS": "1"})
    assert eastmoney_source._normalize_etf_symbol("02800", "HK") == "2800.HK"


@pytest.mark.anyio
async def test_eastmoney_price_rejects_unsupported_interval(eastmoney_source: EastmoneySource):
    query = PriceQuery(symbol="600519.XSHG", market="cn", interval="1Q")

    with pytest.raises(SourceError, match="unsupported interval"):
        await eastmoney_source.fetch_price(query)


@pytest.mark.anyio
async def test_eastmoney_search_chinese_us_stock(eastmoney_source: EastmoneySource):
    """Test searching US stock with Chinese name."""
    results = await eastmoney_source.fetch_equity_search("苹果")
    assert len(results) > 0
    assert any(r["symbol"] == "AAPL" for r in results)
    apple = next(r for r in results if r["symbol"] == "AAPL")
    assert apple["name"] == "苹果"
    assert apple["source"] == "eastmoney"


@pytest.mark.anyio
async def test_eastmoney_search_chinese_hk_stock(eastmoney_source: EastmoneySource):
    """Test searching HK stock with Chinese name."""
    results = await eastmoney_source.fetch_equity_search("腾讯")
    assert len(results) > 0
    assert any(r["symbol"] == "0700.HK" for r in results)
    tencent = next(r for r in results if r["symbol"] == "0700.HK")
    assert "腾讯" in tencent["name"]
    assert tencent["source"] == "eastmoney"


@pytest.mark.anyio
async def test_eastmoney_search_alibaba(eastmoney_source: EastmoneySource):
    """Test searching Alibaba returns both US and HK stocks."""
    results = await eastmoney_source.fetch_equity_search("阿里巴巴")
    assert len(results) > 0
    symbols = [r["symbol"] for r in results]
    assert "BABA" in symbols
    assert "9988.HK" in symbols


@pytest.mark.anyio
async def test_eastmoney_search_english(eastmoney_source: EastmoneySource):
    """Test searching with English name."""
    results = await eastmoney_source.fetch_equity_search("Apple")
    assert len(results) > 0
    assert any(r["symbol"] == "AAPL" for r in results)


@pytest.mark.anyio
async def test_eastmoney_search_cn_stock(eastmoney_source: EastmoneySource):
    """Test searching A-share stock."""
    results = await eastmoney_source.fetch_equity_search("茅台")
    assert len(results) > 0
    assert any(r["symbol"] == "600519.XSHG" for r in results)


@pytest.mark.anyio
async def test_eastmoney_search_ticker_symbol(eastmoney_source: EastmoneySource):
    """Test searching by ticker symbol."""
    results = await eastmoney_source.fetch_equity_search("AAPL")
    assert len(results) > 0
    assert any(r["symbol"] == "AAPL" for r in results)

    results = await eastmoney_source.fetch_equity_search("0700")
    assert len(results) > 0
    # Should include HK stock 0700.HK
    assert any(".HK" in r["symbol"] for r in results)


@pytest.mark.anyio
async def test_eastmoney_search_is_symbol_true(eastmoney_source: EastmoneySource):
    """Test is_symbol=True only matches symbol/code, not name."""
    # Search for "苹果" with is_symbol=True should NOT match AAPL by name
    results = await eastmoney_source.fetch_equity_search("苹果", is_symbol=True)
    # Should not return AAPL because "苹果" doesn't match "AAPL" symbol
    assert not any(r["symbol"] == "AAPL" for r in results)

    # Search for "AAPL" with is_symbol=True should match
    results = await eastmoney_source.fetch_equity_search("AAPL", is_symbol=True)
    assert len(results) > 0
    assert any(r["symbol"] == "AAPL" for r in results)

    # Search for "0700" with is_symbol=True should match HK stock
    results = await eastmoney_source.fetch_equity_search("0700", is_symbol=True)
    assert len(results) > 0
    assert any(r["symbol"] == "0700.HK" for r in results)

    # Search for "600519" with is_symbol=True should match A-share
    results = await eastmoney_source.fetch_equity_search("600519", is_symbol=True)
    assert len(results) > 0
    assert any(r["symbol"] == "600519.XSHG" for r in results)


@pytest.mark.anyio
async def test_eastmoney_search_is_symbol_false(eastmoney_source: EastmoneySource):
    """Test is_symbol=False matches both symbol and name (default behavior)."""
    # Default behavior: search by name should work
    results = await eastmoney_source.fetch_equity_search("苹果", is_symbol=False)
    assert len(results) > 0
    assert any(r["symbol"] == "AAPL" for r in results)

    # Search by symbol should also work
    results = await eastmoney_source.fetch_equity_search("AAPL", is_symbol=False)
    assert len(results) > 0
    assert any(r["symbol"] == "AAPL" for r in results)
