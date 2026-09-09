from datetime import date, datetime

from openbb_finance.sources.futunn import (
    _extract_calendar_records,
    _extract_flash_news_records,
    _normalize_calendar,
    _normalize_news,
    _to_futunn_news_keyword,
)


def test_futunn_calendar_extracts_nested_records():
    payload = {
        "data": {
            "list": {
                "2026/04/29": [
                    {
                        "itemType": 1001,
                        "itemData": {
                            "timestamp": "1777392000",
                            "title": "ICBC released earnings report",
                            "stockMarket": "HK",
                        },
                    }
                ]
            }
        }
    }

    records = _extract_calendar_records(payload)
    result = _normalize_calendar(records[0])

    assert result["date"] == date(2026, 4, 29)
    assert result["country"] == "HK"
    assert result["event"] == "ICBC released earnings report"
    assert result["source"] == "futunn"
    # 可选响应字段缺失时用 None 表达，不再填充空字符串。
    assert result["category"] is None
    assert result["importance"] is None


def test_futunn_calendar_normalizes_empty_strings_and_preserves_zero_values():
    result = _normalize_calendar(
        {
            "itemData": {
                "timestamp": "1777392000",
                "country": "",
                "region": "CN",
                "category": "",
                "event": "",
                "name": "CPI yoy",
                "star": 0,
                "forecast": 0,
                "previous": "1.0",
            }
        }
    )

    # 空字符串视为缺失；回退链继续取到 region/name。
    assert result["country"] == "CN"
    assert result["category"] is None
    assert result["event"] == "CPI yoy"
    # 真实零值保留：importance=0 -> "0"，forecast=0 优先于 consensus。
    assert result["importance"] == "0"
    assert result["consensus"] == 0


def test_futunn_calendar_consensus_falls_back_when_forecast_missing():
    result = _normalize_calendar(
        {
            "itemData": {
                "timestamp": "1777392000",
                "event": "GDP qoq",
                "consensus": "2.1",
            }
        }
    )

    assert result["consensus"] == "2.1"
    assert result["actual"] is None


def test_futunn_news_normalizes_search_records():
    result = _normalize_news(
        {
            "title": "SPY、QQQ、<em>AAPL</em>",
            "publish_time": "1777467758",
            "url": "https://news.futunn.com/post/72302179",
        },
        query="AAPL",
    )

    assert result["date"] == datetime.fromtimestamp(1777467758)
    assert result["title"] == "SPY、QQQ、AAPL"
    assert result["url"] == "https://news.futunn.com/post/72302179"
    assert result["symbols"] == "AAPL"


def test_futunn_news_uses_plain_cn_symbol_keyword_and_openbb_symbol_output():
    assert _to_futunn_news_keyword("000657.XSHE") == "000657"

    result = _normalize_news(
        {
            "title": "中钨高新新闻",
            "publish_time": "1777467758",
            "url": "https://news.futunn.com/post/72302179",
        },
        query="000657.XSHE",
    )

    assert result["symbols"] == "000657.XSHE"


def test_futunn_flash_news_extracts_nested_records():
    payload = {
        "data": {
            "data": {
                "news": [
                    {
                        "content": "以色列总统：英国政府必须采取紧急行动。",
                        "detailUrl": "https://news.futunn.com/flash/20234893",
                        "time": "1777468837",
                    }
                ]
            }
        }
    }

    records = _extract_flash_news_records(payload)
    result = _normalize_news(records[0])

    assert result["date"] == datetime.fromtimestamp(1777468837)
    assert result["title"] == "以色列总统：英国政府必须采取紧急行动。"
    assert result["url"] == "https://news.futunn.com/flash/20234893"
