"""Data endpoint tests against a fake schwabdev client with doc-shaped fixtures."""

from __future__ import annotations

import calendar
import datetime
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from schwab_api.main import create_app
from schwab_fakes import make_config, make_row

QUOTE_FIXTURE = {
    "AAPL": {
        "assetMainType": "Equity",
        "assetSubType": "COE",
        "symbol": "AAPL",
        "quote": {
            "askPrice": 229.17,
            "askSize": 5,
            "bidPrice": 229.15,
            "bidSize": 14,
            "lastPrice": 229.18,
            "regularMarketLastPrice": 229.18,
            "totalVolume": 45089766,
        },
    }
}

HISTORICAL_FIXTURE = {
    "symbol": "AAPL",
    "empty": False,
    "candles": [
        {"open": 227.5, "high": 229.6, "low": 227.34, "close": 229.18, "volume": 45089766, "datetime": 1737061200000}
    ],
}

CHAINS_FIXTURE = {
    "symbol": "AAPL",
    "status": "SUCCESS",
    "callExpDateMap": {"2025-02-21:2": {"220.0": [{"putCall": "CALL", "strikePrice": 220.0, "daysToExpiration": 30}]}},
    "putExpDateMap": {},
}

EXPIRATIONS_FIXTURE = {"symbol": "AAPL", "expirationDates": ["2025-02-21", "2025-03-21"]}

MARKET_HOURS_FIXTURE = {
    "equity": {
        "date": "2025-01-16",
        "marketType": "EQUITY",
        "isOpen": True,
        "sessionHours": [{"sessionType": "regularMarket", "start": "2025-01-16T09:30:00-05:00"}],
    }
}


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code
        self.headers = {"content-type": "application/json"}

    @property
    def content(self) -> bytes:
        return json.dumps(self.payload).encode()


class FakeClient:
    """Records schwabdev-shaped kwargs; returns canned payloads."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def _record(self, name: str, **kwargs):
        self.calls.append((name, kwargs))
        payloads = {
            "quotes": QUOTE_FIXTURE,
            "price_history": HISTORICAL_FIXTURE,
            "option_chains": CHAINS_FIXTURE,
            "option_expiration_chain": EXPIRATIONS_FIXTURE,
            "market_hours": MARKET_HOURS_FIXTURE,
        }
        return FakeResponse(payloads.get(name, {"ok": True}))

    def quotes(self, symbols, fields=None, indicative=False):
        return self._record("quotes", symbols=symbols, fields=fields, indicative=indicative)

    def price_history(
        self,
        symbol,
        periodType=None,
        period=None,
        frequencyType=None,
        frequency=None,
        startDate=None,
        endDate=None,
        needExtendedHoursData=None,
        needPreviousClose=None,
    ):
        return self._record(
            "price_history",
            symbol=symbol,
            periodType=periodType,
            period=period,
            frequencyType=frequencyType,
            frequency=frequency,
            startDate=startDate,
            endDate=endDate,
            needExtendedHoursData=needExtendedHoursData,
            needPreviousClose=needPreviousClose,
        )

    def instruments(self, symbols, projection):
        return self._record("instruments", symbols=symbols, projection=projection)

    def instrument_cusip(self, cusip_id):
        return self._record("instrument_cusip", cusip_id=cusip_id)

    def movers(self, symbol, sort=None, frequency=None):
        return self._record("movers", symbol=symbol, sort=sort, frequency=frequency)

    def option_chains(
        self,
        symbol,
        contractType=None,
        strikeCount=None,
        includeUnderlyingQuote=None,
        strategy=None,
        interval=None,
        strike=None,
        range=None,
        fromDate=None,
        toDate=None,
        volatility=None,
        underlyingPrice=None,
        interestRate=None,
        daysToExpiration=None,
        expMonth=None,
        optionType=None,
        entitlement=None,
    ):
        return self._record(
            "option_chains",
            symbol=symbol,
            contractType=contractType,
            strikeCount=strikeCount,
            includeUnderlyingQuote=includeUnderlyingQuote,
            strategy=strategy,
            interval=interval,
            strike=strike,
            range=range,
            fromDate=fromDate,
            toDate=toDate,
            volatility=volatility,
            underlyingPrice=underlyingPrice,
            interestRate=interestRate,
            daysToExpiration=daysToExpiration,
            expMonth=expMonth,
            optionType=optionType,
            entitlement=entitlement,
        )

    def option_expiration_chain(self, symbol):
        return self._record("option_expiration_chain", symbol=symbol)

    def market_hours(self, symbols, date=None):
        return self._record("market_hours", symbols=symbols, date=date)


class StubManager:
    def __init__(self, fake: FakeClient | None):
        self._fake = fake

    def get(self):
        if self._fake is None:
            from schwab_api.client import NotAuthenticatedError

            raise NotAuthenticatedError("no Schwab tokens stored; authorize via POST /api/v1/auth/start")
        return self._fake

    def reset(self):
        pass


@pytest.fixture()
def fake():
    return FakeClient()


@pytest.fixture()
def api(config, store, fake):
    app = create_app(config=config, store=store)
    app.state.clients = StubManager(fake)
    return TestClient(app)


def epoch_ms(year: int, month: int, day: int) -> int:
    ts = (year, month, day, 0, 0, 0)
    return calendar.timegm(ts) * 1000


# ---- interval / epoch mapping (core regression table) ------------------------


@pytest.mark.parametrize(
    ("interval", "expected_type", "expected_freq"),
    [
        ("1m", "minute", 1),
        ("5m", "minute", 5),
        ("10m", "minute", 10),
        ("15m", "minute", 15),
        ("30m", "minute", 30),
        ("1d", "daily", 1),
        ("1w", "weekly", 1),
        ("1M", "monthly", 1),
    ],
)
def test_historical_interval_mapping(api, fake, interval, expected_type, expected_freq):
    response = api.get("/api/v1/equity/price/historical", params={"symbol": "AAPL", "interval": interval})
    assert response.status_code == 200
    _, kwargs = fake.calls[0]
    assert kwargs["frequencyType"] == expected_type
    assert kwargs["frequency"] == expected_freq


def test_historical_daily_weekly_monthly_carry_period_type(api, fake):
    """Schwab range queries default periodType=DAY, which only allows minute —
    daily/weekly/monthly must send periodType=year (production-verified)."""
    for interval in ("1d", "1w", "1M"):
        api.get("/api/v1/equity/price/historical", params={"symbol": "AAPL", "interval": interval})
        _, kwargs = fake.calls[-1]
        assert kwargs["periodType"] == "year"


def test_historical_dates_converted_to_epoch_ms(api, fake):
    api.get(
        "/api/v1/equity/price/historical",
        params={"symbol": "AAPL", "interval": "1d", "start": "2024-01-15", "end": "2024-01-16"},
    )
    _, kwargs = fake.calls[0]
    assert kwargs["startDate"] == datetime.datetime(2024, 1, 15, tzinfo=datetime.timezone.utc)
    assert kwargs["endDate"] == datetime.datetime(2024, 1, 16, tzinfo=datetime.timezone.utc)
    # and the epoch conversion itself
    assert epoch_ms(2024, 1, 15) == 1705276800000


def test_historical_datetime_with_timezone(api, fake):
    api.get(
        "/api/v1/equity/price/historical",
        params={"symbol": "AAPL", "interval": "1m", "start": "2024-01-15T09:30:00-05:00"},
    )
    _, kwargs = fake.calls[0]
    assert kwargs["startDate"] == datetime.datetime(2024, 1, 15, 14, 30, tzinfo=datetime.timezone.utc)


def test_historical_rejects_unknown_interval(api):
    response = api.get("/api/v1/equity/price/historical", params={"symbol": "AAPL", "interval": "2h"})
    assert response.status_code == 422


def test_historical_rejects_bad_date(api):
    response = api.get(
        "/api/v1/equity/price/historical", params={"symbol": "AAPL", "interval": "1d", "start": "01/15/2024"}
    )
    assert response.status_code == 422


# ---- passthrough behavior -----------------------------------------------------


def test_quote_passthrough(api, fake):
    response = api.get("/api/v1/equity/price/quote", params={"symbols": "AAPL,MSFT", "indicative": True})
    assert response.status_code == 200
    assert response.json() == QUOTE_FIXTURE
    _, kwargs = fake.calls[0]
    assert kwargs["symbols"] == "AAPL,MSFT"
    assert kwargs["indicative"] is True


def test_fundamental_uses_projection(api, fake):
    api.get("/api/v1/equity/fundamental", params={"symbol": "AAPL"})
    name, kwargs = fake.calls[0]
    assert name == "instruments"
    assert kwargs["projection"] == "fundamental"


def test_search_rejects_bad_projection(api):
    assert api.get("/api/v1/equity/search", params={"symbol": "AAPL", "projection": "weird"}).status_code == 422


def test_movers_passes_index(api, fake):
    api.get("/api/v1/equity/movers", params={"index": "$SPX", "sort": "VOLUME", "frequency": 0})
    name, kwargs = fake.calls[0]
    assert name == "movers"
    assert kwargs == {"symbol": "$SPX", "sort": "VOLUME", "frequency": 0}


def test_movers_rejects_bad_frequency(api):
    assert api.get("/api/v1/equity/movers", params={"index": "$SPX", "frequency": 7}).status_code == 422


def test_option_chains_maps_snake_case_to_camel_case(api, fake):
    response = api.get(
        "/api/v1/options/chains",
        params={
            "symbol": "AAPL",
            "contract_type": "CALL",
            "strike_count": 10,
            "dte": 30,
            "range": "NTM",
            "from_date": "2025-01-15",
            "exp_month": "JAN",
        },
    )
    assert response.status_code == 200
    assert response.json() == CHAINS_FIXTURE
    _, kwargs = fake.calls[0]
    assert kwargs["contractType"] == "CALL"
    assert kwargs["strikeCount"] == 10
    assert kwargs["daysToExpiration"] == 30
    assert kwargs["range"] == "NTM"
    assert kwargs["fromDate"] == "2025-01-15"
    assert kwargs["expMonth"] == "JAN"


def test_option_chains_rejects_bad_contract_type(api):
    response = api.get("/api/v1/options/chains", params={"symbol": "AAPL", "contract_type": "BOTH"})
    assert response.status_code == 422


def test_expirations_passthrough(api, fake):
    response = api.get("/api/v1/options/expirations", params={"symbol": "AAPL"})
    assert response.status_code == 200
    assert response.json() == EXPIRATIONS_FIXTURE


def test_market_hours_multiple_markets(api, fake):
    api.get("/api/v1/market/hours", params={"markets": "equity,option", "date": "2025-01-16"})
    _, kwargs = fake.calls[0]
    assert kwargs["symbols"] == "equity,option"
    assert kwargs["date"] == "2025-01-16"


# ---- degradation: unauthenticated / API key ----------------------------------


def test_unauthenticated_data_endpoint_is_503_healthz_still_ok(config, store):
    with TestClient(create_app(config=config, store=store)) as client:
        response = client.get("/api/v1/equity/price/quote", params={"symbols": "AAPL"})
        assert response.status_code == 503
        assert "authorize" in response.json()["detail"]
        assert client.get("/healthz").status_code == 200
        status = client.get("/api/v1/status").json()
        assert status["authenticated"] is False


def test_api_key_required_on_data_endpoints_only(tmp_path):
    from schwab_api.store import TokenStore

    config = make_config(api_key="sekrit")
    store = TokenStore(str(tmp_path / "tokens.db"))
    store.write(make_row())
    app = create_app(config=config, store=store)
    app.state.clients = StubManager(FakeClient())
    with TestClient(app) as client:
        assert client.get("/api/v1/equity/price/quote", params={"symbols": "AAPL"}).status_code == 401
        headers = {"X-API-Key": "sekrit"}
        assert client.get("/api/v1/equity/price/quote", params={"symbols": "AAPL"}, headers=headers).status_code == 200
        # exempt paths
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/v1/status").status_code == 200
        assert client.post("/api/v1/auth/start").status_code == 409  # authenticated -> 409, so no key needed
