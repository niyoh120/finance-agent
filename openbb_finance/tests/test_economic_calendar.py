from datetime import date
from types import SimpleNamespace

import pytest
from openbb_finance.models.economic_calendar import FinanceEconomicCalendarFetcher


class FakeRegistry:
    def __init__(self) -> None:
        self.source = SimpleNamespace(name="futunn", priority=100, enabled=True, fetch_economic_calendar=self.fetch)
        self.received: tuple[date, date] | None = None

    def ordered_by_names(self, names):
        assert names == ["futunn", "akshare", "openbb"]
        return [self.source]

    async def fetch(self, start_date: date, end_date: date):
        self.received = (start_date, end_date)
        return [
            {
                "date": start_date,
                "country": "US",
                "event": "GDP",
                "source": "futunn",
            }
        ]


@pytest.mark.anyio
async def test_economic_calendar_defaults_missing_dates():
    registry = FakeRegistry()
    query = FinanceEconomicCalendarFetcher.transform_query({})

    result = await FinanceEconomicCalendarFetcher.aextract_data(query, credentials=None, registry=registry)

    assert registry.received is not None
    start_date, end_date = registry.received
    assert start_date == end_date == date.today()
    assert result[0]["date"] == date.today()
