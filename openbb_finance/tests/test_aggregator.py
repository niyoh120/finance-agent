from types import SimpleNamespace

import pytest
from openbb_finance.aggregator import aggregate_records


@pytest.mark.anyio
async def test_aggregate_records_first_source_wins_per_field():
    """List order is precedence: the first source's value for a field is kept,
    later sources only fill fields the first did not populate."""

    first = SimpleNamespace(name="baostock", enabled=True)
    second = SimpleNamespace(name="akshare", enabled=True)

    async def fetch(source):
        if source.name == "baostock":
            # gdp_qoq is explicitly None so we can verify the second source fills it.
            return [{"date": "2024-Q1", "gdp": 100, "gdp_yoy": 5.0, "gdp_qoq": None}]
        return [{"date": "2024-Q1", "gdp": 101, "gdp_yoy": 5.1, "gdp_qoq": 1.2}]

    # [first, second]: first wins gdp/gdp_yoy; second fills the missing gdp_qoq.
    result = await aggregate_records([first, second], fetch, key_fields=("date",))

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
