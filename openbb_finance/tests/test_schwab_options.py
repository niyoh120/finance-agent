"""Schwab option chain flattening + SchwabSource.fetch_options_chain tests.

The fixture mirrors a real schwab-api response (AAPL, 2026-09, live capture):
map keys "YYYY-MM-DD:N", strike keys as strings, contract objects with
camelCase fields. Field conventions must match the CV chain model because the
CLI aggregates both sources on (expiration, strike, option_type).
"""

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from openbb_finance.config import SourceConfig
from openbb_finance.models.schwab_options_chain import flatten_schwab_chain
from openbb_finance.sources.base import SourceError
from openbb_finance.sources.schwab import SchwabSource

pytestmark = pytest.mark.anyio


def _contract(**overrides):
    base = {
        "putCall": "CALL",
        "symbol": "AAPL  260909C00317500",
        "description": "AAPL 09/09/2026 317.50 C",
        "exchangeName": "OPR",
        "bid": 5.0,
        "ask": 5.3,
        "last": 5.07,
        "mark": 5.15,
        "bidSize": 57,
        "askSize": 16,
        "highPrice": 10.6,
        "lowPrice": 4.25,
        "openPrice": 10.6,
        "closePrice": 5.15,
        "totalVolume": 1976,
        "tradeTimeInLong": 1788551963854,
        "quoteTimeInLong": 1788551999923,
        "netChange": -0.08,
        "volatility": 25.62,
        "delta": 0.606,
        "gamma": 0.041,
        "theta": -0.382,
        "vega": 0.143,
        "openInterest": 360,
        "theoreticalOptionValue": 5.097,
        "strikePrice": 317.5,
        "expirationDate": "2026-09-09T20:00:00.000+00:00",
        "daysToExpiration": 3,
        "multiplier": 100.0,
        "percentChange": -1.55,
        "exerciseType": "A",
        "breakEven": 322.65,
    }
    base.update(overrides)
    return base


CHAIN_FIXTURE = {
    "symbol": "AAPL",
    "status": "SUCCESS",
    "underlyingPrice": 319.97,
    "volatility": 29.0,
    "daysToExpiration": 3,
    "interestRate": 3.757,
    "isIndex": False,
    "numberOfContracts": 4,
    "callExpDateMap": {
        "2026-09-09:3": {
            "317.5": [_contract()],
            "320.0": [_contract(strikePrice=320.0, symbol="AAPL  260909C00320000", delta=0.52)],
        }
    },
    "putExpDateMap": {
        "2026-09-09:3": {
            "317.5": [
                _contract(
                    putCall="PUT",
                    symbol="AAPL  260909P00317500",
                    delta=-0.39,
                    exerciseType="E",
                )
            ],
        }
    },
}


# ---- flattening ----------------------------------------------------------------


def test_flatten_produces_one_record_per_contract():
    records = flatten_schwab_chain(CHAIN_FIXTURE)

    assert len(records) == 3
    assert {(r["expiration"], r["strike"], r["option_type"]) for r in records} == {
        (date(2026, 9, 9), 317.5, "call"),
        (date(2026, 9, 9), 320.0, "call"),
        (date(2026, 9, 9), 317.5, "put"),
    }


def test_flatten_maps_fields_to_cv_model_conventions():
    records = flatten_schwab_chain(CHAIN_FIXTURE, query_symbol="AAPL")
    call = next(r for r in records if r["option_type"] == "call" and r["strike"] == 317.5)

    assert call["symbol"] == "AAPL"
    assert call["contract_symbol"] == "AAPL260909C00317500"  # spaces stripped
    assert call["expiration"] == date(2026, 9, 9)
    assert call["strike"] == 317.5
    assert call["option_type"] == "call"
    assert call["bid"] == 5.0
    assert call["bid_size"] == 57.0
    assert call["ask"] == 5.3
    assert call["ask_size"] == 16.0
    assert call["mark"] == 5.15
    assert call["theoretical_price"] == 5.097
    assert call["break_even_price"] == 322.65
    assert call["open_interest"] == 360.0
    assert call["volume"] == 1976.0
    assert call["open"] == 10.6
    assert call["high"] == 10.6
    assert call["low"] == 4.25
    assert call["close"] == 5.15
    assert call["change"] == -0.08
    assert call["change_percent"] == -1.55
    assert call["last_trade_price"] == 5.07
    assert call["delta"] == 0.606
    assert call["gamma"] == 0.041
    assert call["theta"] == -0.382
    assert call["vega"] == 0.143
    # Schwab volatility is a percent; normalized to the CV decimal convention.
    assert call["implied_volatility"] == pytest.approx(0.2562)
    assert call["exercise_style"] == "american"
    assert call["contract_size"] == 100.0
    assert call["dte"] == 3
    assert call["underlying_price"] == 319.97
    assert call["underlying_symbol"] == "AAPL"
    assert call["fetched_at"] == datetime.fromtimestamp(1788551999923 / 1000, tz=timezone.utc)


def test_flatten_put_row_maps_exercise_type_european():
    records = flatten_schwab_chain(CHAIN_FIXTURE)
    put = next(r for r in records if r["option_type"] == "put")

    assert put["contract_symbol"] == "AAPL260909P00317500"
    assert put["exercise_style"] == "european"
    assert put["delta"] == -0.39


def test_flatten_returns_empty_for_malformed_payload():
    assert flatten_schwab_chain({}) == []
    assert flatten_schwab_chain({"callExpDateMap": None, "putExpDateMap": {}}) == []


def test_flatten_normalizes_negative_iv_sentinel_to_none():
    # Schwab marks contracts without IV with volatility = -999 (live-verified).
    fixture = {
        "symbol": "AAPL",
        "callExpDateMap": {"2026-09-09:3": {"317.5": [_contract(volatility=-999)]}},
    }

    records = flatten_schwab_chain(fixture)

    assert records[0]["implied_volatility"] is None


# ---- aggregation (_options_chain_execute in openbb-agent-cli) -------------------


def _schwab_chain_rows() -> list[dict]:
    """In-window Schwab rows: pricing always populated, vwap unknown."""
    return [
        {
            "symbol": "SPY",
            "expiration": date(2026, 9, 9),
            "strike": 500.0,
            "option_type": "call",
            "bid": 5.0,
            "ask": 5.3,
            "delta": 0.6,
            "vwap": None,
            "dte": 3,
            "open_interest": 1000.0,
        },
        {
            "symbol": "SPY",
            "expiration": date(2026, 9, 9),
            "strike": 505.0,
            "option_type": "call",
            "bid": 3.0,
            "ask": 3.2,
            "delta": 0.45,
            "vwap": None,
            "dte": 3,
            "open_interest": 900.0,
        },
    ]


def _cv_chain_rows() -> list[dict]:
    """CV rows: bid/ask null (subscription gap), plus an out-of-window row."""
    return [
        {
            "symbol": "SPY",
            "expiration": date(2026, 9, 9),
            "strike": 500.0,
            "option_type": "call",
            "bid": None,
            "ask": None,
            "delta": 0.61,
            "vwap": 5.1,
            "dte": 3,
            "open_interest": 1001.0,
            "underlying_price": 501.0,
        },
        {
            # far-dated CV-only contract (outside the Schwab window)
            "symbol": "SPY",
            "expiration": date(2026, 12, 18),
            "strike": 700.0,
            "option_type": "call",
            "bid": 2.0,
            "ask": 2.5,
            "delta": 0.1,
            "vwap": 2.2,
            "dte": 100,
            "open_interest": 5000.0,
            "underlying_price": 501.0,
        },
    ]


def _patch_aggregation(
    monkeypatch: pytest.MonkeyPatch,
    *,
    schwab_records: list[dict] | None = None,
    cv_records: list[dict] | None = None,
    cv_total: int = 0,
    cv_enabled: bool = True,
    schwab_enabled: bool = True,
    cv_error: Exception | None = None,
) -> dict:
    """Wire fakes into _aggregate_options_chain / _options_chain_execute."""
    import openbb_agent_cli.executors as executors_module
    import openbb_finance.registry as registry_module
    from openbb_finance.models.equity_options_chain import FinanceOptionsChainFetcher

    calls: dict = {}

    class FakeRegistry:
        def __init__(self):
            self._schwab = SimpleNamespace(
                name="schwab",
                enabled=schwab_enabled,
                fetch_options_chain=self._fetch_schwab_chain,
            )

        async def _fetch_schwab_chain(self, symbol, *, dte, strike_count, range_=None, strategy=None):
            calls["schwab"] = {
                "symbol": symbol,
                "dte": dte,
                "strike_count": strike_count,
                "range": range_,
                "strategy": strategy,
            }
            return {"records": list(schwab_records or []), "contract_count": len(schwab_records or [])}

        def get(self, name):
            return self._schwab if name == "schwab" else None

    async def fake_aextract(query, credentials, **kwargs):
        calls["cv"] = True
        if cv_error is not None:
            raise cv_error
        return {"records": list(cv_records or []), "contract_count": cv_total}

    monkeypatch.setattr(registry_module, "build_default_registry", FakeRegistry)
    monkeypatch.setattr(FinanceOptionsChainFetcher, "aextract_data", fake_aextract)
    monkeypatch.setattr(executors_module, "_cv_api_key", lambda: "k" if cv_enabled else "")
    return calls


def test_aggregate_schwab_wins_fields_cv_fills_nulls(monkeypatch: pytest.MonkeyPatch):
    from openbb_agent_cli.executors import _options_chain_execute

    _patch_aggregation(
        monkeypatch,
        schwab_records=_schwab_chain_rows(),
        cv_records=_cv_chain_rows(),
        cv_total=12345,
    )

    records, meta = _options_chain_execute(
        {"symbol": "SPY", "dte": 10, "strike_count": 30, "sort_by": "open_interest", "sort_dir": "desc", "limit": 0}
    )

    by_key = {(r["expiration"], r["strike"], r["option_type"]): r for r in records}
    assert set(by_key) == {
        (date(2026, 9, 9), 500.0, "call"),
        (date(2026, 9, 9), 505.0, "call"),
        (date(2026, 12, 18), 700.0, "call"),  # CV-only out-of-window row survives
    }

    in_window = by_key[(date(2026, 9, 9), 500.0, "call")]
    # CV bid/ask are null -> filled from schwab
    assert in_window["bid"] == 5.0
    assert in_window["ask"] == 5.3
    # both sources populated -> schwab (first source) wins delta/OI
    assert in_window["delta"] == 0.6
    assert in_window["open_interest"] == 1000.0
    # schwab left vwap null -> CV fills it
    assert in_window["vwap"] == 5.1

    cv_only = by_key[(date(2026, 12, 18), 700.0, "call")]
    assert cv_only["bid"] == 2.0
    assert cv_only["open_interest"] == 5000.0

    # Zero source annotations: shape identical to the single-source output.
    annotated = [key for row in records for key in row if key.endswith("_source")]
    assert annotated == []

    assert meta["total"] == 12345  # CV server-reported count
    assert meta["sources_used"] == ["schwab", "convexvalue"]


def test_aggregate_cv_failure_degrades_to_schwab_only(monkeypatch: pytest.MonkeyPatch):
    from openbb_agent_cli.executors import _options_chain_execute

    _patch_aggregation(
        monkeypatch,
        schwab_records=_schwab_chain_rows(),
        cv_records=_cv_chain_rows(),
        cv_error=RuntimeError("CV down"),
    )

    records, meta = _options_chain_execute({"symbol": "SPY", "dte": 10, "strike_count": 30, "limit": 0})

    assert len(records) == 2
    assert meta["sources_used"] == ["schwab"]
    # CV server total unavailable -> honest fallback to the merged row count
    assert meta["total"] == 2


def test_aggregate_schwab_disabled_degrades_to_cv_only(monkeypatch: pytest.MonkeyPatch):
    from openbb_agent_cli.executors import _options_chain_execute

    _patch_aggregation(
        monkeypatch,
        schwab_records=_schwab_chain_rows(),
        cv_records=_cv_chain_rows(),
        cv_total=2,
        schwab_enabled=False,
    )

    records, meta = _options_chain_execute({"symbol": "SPY", "dte": 10, "strike_count": 30, "limit": 0})

    assert len(records) == 2  # full CV chain, unfiltered
    assert meta["sources_used"] == ["convexvalue"]


def test_aggregate_clips_loose_schwab_dte(monkeypatch: pytest.MonkeyPatch):
    """Schwab's server-side daysToExpiration is loose; the declared window is
    enforced locally so in-window rows always satisfy dte <= --dte."""
    from openbb_agent_cli.executors import _options_chain_execute

    schwab_rows = [
        *_schwab_chain_rows(),
        {**_schwab_chain_rows()[0], "strike": 400.0, "dte": 131, "open_interest": 99999.0},
    ]
    _patch_aggregation(
        monkeypatch,
        schwab_records=schwab_rows,
        cv_records=_cv_chain_rows(),
        cv_total=12345,
    )

    records, meta = _options_chain_execute(
        {"symbol": "SPY", "dte": 10, "strike_count": 30, "source": "schwab", "limit": 0}
    )

    assert all(r["dte"] <= 10 for r in records)
    assert len(records) == 2
    assert meta["sources_used"] == ["schwab"]


def test_source_schwab_single_source_skips_cv(monkeypatch: pytest.MonkeyPatch):
    from openbb_agent_cli.executors import _options_chain_execute

    calls = _patch_aggregation(monkeypatch, schwab_records=_schwab_chain_rows(), cv_records=_cv_chain_rows())

    records, meta = _options_chain_execute(
        {
            "symbol": "SPY",
            "dte": 7,
            "strike_count": 10,
            "source": "schwab",
            "range_": "ITM",
            "strategy": "VERTICAL",
            "limit": 0,
        }
    )

    assert "cv" not in calls
    assert calls["schwab"] == {
        "symbol": "SPY",
        "dte": 7,
        "strike_count": 10,
        "range": "ITM",
        "strategy": "VERTICAL",
    }
    assert len(records) == 2
    assert meta["sources_used"] == ["schwab"]


def test_source_cv_single_source_applies_local_window(monkeypatch: pytest.MonkeyPatch):
    from openbb_agent_cli.executors import _options_chain_execute

    calls = _patch_aggregation(
        monkeypatch,
        cv_records=_cv_chain_rows(),
        cv_total=456,
    )

    records, meta = _options_chain_execute({"symbol": "SPY", "dte": 10, "strike_count": 1, "source": "cv", "limit": 0})

    assert calls["cv"] is True
    # dte=100 row filtered out; strike_count=1 keeps the single nearest level
    # to underlying_price=501 (strike 500) per expiration.
    assert [(r["strike"], r["dte"]) for r in records] == [(500.0, 3)]
    assert meta["total"] == 456
    assert meta["sources_used"] == ["convexvalue"]


def test_options_chain_requires_dte_and_strike_count():
    from openbb_agent_cli.executors import _options_chain_execute

    with pytest.raises(ValueError, match="dte"):
        _options_chain_execute({"symbol": "SPY"})
    with pytest.raises(ValueError, match="dte"):
        _options_chain_execute({"symbol": "SPY", "dte": 10})
    with pytest.raises(ValueError, match="strike_count"):
        _options_chain_execute({"symbol": "SPY", "dte": 10, "strike_count": None})


def test_filter_cv_chain_window_keeps_nearest_strikes_per_expiration():
    from openbb_agent_cli.executors import _filter_cv_chain_window

    def row(expiration, strike, dte, underlying):
        return {
            "expiration": expiration,
            "strike": strike,
            "dte": dte,
            "underlying_price": underlying,
            "option_type": "call",
        }

    records = [
        row(date(2026, 9, 9), 400.0, 3, 501.0),
        row(date(2026, 9, 9), 500.0, 3, 501.0),
        row(date(2026, 9, 9), 600.0, 3, 501.0),
        row(date(2026, 12, 18), 700.0, 100, None),  # dte beyond window -> dropped
    ]

    kept = _filter_cv_chain_window(records, dte=10, strike_count=1)

    assert [(r["strike"], r["dte"]) for r in kept] == [(500.0, 3)]


# ---- SchwabSource.fetch_options_chain -------------------------------------------


class FakeChainSchwab(SchwabSource):
    def __init__(self, fixture=None):
        super().__init__(SourceConfig(name="schwab", enabled=True, base_url="http://127.0.0.1:8010"))
        self.fixture = fixture if fixture is not None else CHAIN_FIXTURE
        self.calls = []

    async def _get(self, path, params):
        self.calls.append((path, dict(params)))
        return self.fixture


async def test_fetch_options_chain_requires_dte_and_strike_count():
    source = FakeChainSchwab()

    with pytest.raises(SourceError, match="dte"):
        await source.fetch_options_chain("AAPL", dte=None, strike_count=30)
    with pytest.raises(SourceError, match="strike_count"):
        await source.fetch_options_chain("AAPL", dte=10, strike_count=None)


async def test_fetch_options_chain_passes_filters_and_returns_contract_count():
    source = FakeChainSchwab()

    data = await source.fetch_options_chain("aapl", dte=10, strike_count=30)

    assert source.calls == [
        (
            "/api/v1/options/chains",
            {"symbol": "AAPL", "dte": 10, "strike_count": 30},
        )
    ]
    assert data["contract_count"] == 4  # server-reported numberOfContracts
    assert len(data["records"]) == 3
    assert data["records"][0]["expiration"] == date(2026, 9, 9)


async def test_fetch_options_chain_forwards_range_and_strategy():
    source = FakeChainSchwab()

    await source.fetch_options_chain("SPY", dte=7, strike_count=10, range_="ITM", strategy="VERTICAL")

    assert source.calls[0][1]["range"] == "ITM"
    assert source.calls[0][1]["strategy"] == "VERTICAL"


async def test_fetch_options_chain_falls_back_to_record_count():
    fixture = {**CHAIN_FIXTURE, "numberOfContracts": None}
    source = FakeChainSchwab(fixture)

    data = await source.fetch_options_chain("AAPL", dte=10, strike_count=30)

    assert data["contract_count"] == 3
