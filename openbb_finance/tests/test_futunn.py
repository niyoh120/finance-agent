from datetime import date

from openbb_finance.sources.futunn import _extract_calendar_records, _normalize_calendar


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
