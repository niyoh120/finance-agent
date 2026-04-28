from types import SimpleNamespace

import pytest
from openbb_finance.aggregator import aggregate_records


@pytest.mark.anyio
async def test_aggregate_records_keeps_highest_priority_field_values():
    high = SimpleNamespace(name="baostock", priority=90, enabled=True)
    low = SimpleNamespace(name="akshare", priority=70, enabled=True)

    async def fetch(source):
        if source.name == "baostock":
            return [{"date": "2024-Q1", "gdp": 100, "gdp_yoy": 5.0}]
        return [{"date": "2024-Q1", "gdp": 101, "gdp_yoy": 5.1, "gdp_qoq": 1.2}]

    result = await aggregate_records([low, high], fetch, key_fields=("date",))

    assert result == [
        {
            "date": "2024-Q1",
            "date_source": "baostock",
            "gdp": 100,
            "gdp_source": "baostock",
            "gdp_yoy": 5.0,
            "gdp_yoy_source": "baostock",
            "gdp_qoq": 1.2,
            "gdp_qoq_source": "akshare",
        }
    ]
