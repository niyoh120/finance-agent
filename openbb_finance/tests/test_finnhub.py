from datetime import date, datetime

import pytest
from openbb_finance.config import SourceConfig
from openbb_finance.sources.finnhub import FinnhubSource

pytestmark = pytest.mark.anyio


def test_finnhub_reads_custom_base_url():
    source = FinnhubSource(
        SourceConfig(
            name="finnhub",
            enabled=True,
            priority=102,
            api_key="token",
            base_url="https://proxy.example.com/finnhub/",
        )
    )

    assert source.base_url == "https://proxy.example.com/finnhub"


def test_finnhub_disables_without_api_key():
    source = FinnhubSource(SourceConfig(name="finnhub", enabled=True, priority=102, api_key=""))

    assert source.enabled is False


async def test_finnhub_company_news_normalizes_records():
    class FakeFinnhubSource(FinnhubSource):
        async def _get(self, path, params):
            assert path == "/company-news"
            assert params["symbol"] == "AAPL"
            assert "from" in params
            assert "to" in params
            return [
                {
                    "datetime": 1782629364,
                    "headline": "Apple news",
                    "source": "Reuters",
                    "summary": "Summary",
                    "url": "https://example.com/news",
                    "related": "AAPL",
                    "image": "https://example.com/image.jpg",
                },
                {"datetime": "", "headline": "No date"},
            ]

    source = FakeFinnhubSource(SourceConfig(name="finnhub", enabled=True, priority=102, api_key="token"))
    result = await source.fetch_news("aapl", limit=5)

    assert result[0] == {
        "date": datetime.fromtimestamp(1782629364),
        "title": "Apple news",
        "author": "Reuters",
        "excerpt": "Summary",
        "body": None,
        "images": "https://example.com/image.jpg",
        "url": "https://example.com/news",
        "symbols": "AAPL",
        "source": "finnhub",
    }
    assert result[1]["title"] == "No date"
    assert isinstance(result[1]["date"], datetime)


async def test_finnhub_world_news_filters_dates_and_limit():
    class FakeFinnhubSource(FinnhubSource):
        async def _get(self, path, params):
            assert path == "/news"
            assert params == {"category": "general"}
            return [
                {"datetime": 1782518400, "headline": "Old"},
                {"datetime": 1782604800, "headline": "Inside"},
                {"datetime": 1782691200, "headline": "Later"},
            ]

    source = FakeFinnhubSource(SourceConfig(name="finnhub", enabled=True, priority=102, api_key="token"))
    start_date = date.fromtimestamp(1782604800)
    end_date = date.fromtimestamp(1782691200)

    filtered = await source.fetch_world_news(limit=10, start_date=start_date, end_date=end_date)
    limited = await source.fetch_world_news(limit=1, start_date=start_date, end_date=end_date)

    assert [item["title"] for item in filtered] == ["Inside", "Later"]
    assert [item["title"] for item in limited] == ["Inside"]
