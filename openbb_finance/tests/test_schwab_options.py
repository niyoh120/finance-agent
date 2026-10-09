"""Schwab option chain flattening + SchwabSource.fetch_options_chain tests.

The fixture mirrors a real schwab-api response (AAPL, 2026-09, live capture):
map keys "YYYY-MM-DD:N", strike keys as strings, contract objects with
camelCase fields. Field conventions must match the CV chain model because the
CLI aggregates both sources on (expiration, strike, option_type).
"""

from datetime import date, datetime, timedelta, timezone
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


# ---- chain execution (_options_chain_execute in openbb-agent-cli) --------------


def _near_exp(days: int = 3) -> date:
    """Expiration a few days after the frozen UTC as_of (deterministic in-window)."""
    return datetime.now(timezone.utc).date() + timedelta(days=days)


def _schwab_chain_rows() -> list[dict]:
    """Schwab rows: pricing always populated, vwap unknown, upstream dte poisoned."""
    exp = _near_exp(3)
    return [
        {
            "symbol": "SPY",
            "expiration": exp,
            "strike": 500.0,
            "option_type": "call",
            "bid": 5.0,
            "ask": 5.3,
            "delta": 0.6,
            "vwap": None,
            "dte": 999,
            "open_interest": 1000.0,
            "underlying_price": 501.0,
        },
        {
            "symbol": "SPY",
            "expiration": exp,
            "strike": 505.0,
            "option_type": "call",
            "bid": 3.0,
            "ask": 3.2,
            "delta": 0.45,
            "vwap": None,
            "dte": 3,
            "open_interest": 900.0,
            "underlying_price": 501.0,
        },
    ]


def _cv_chain_rows() -> list[dict]:
    """CV rows: bid/ask null (subscription gap), plus a CV-only contract that
    sits inside the query window and must be IGNORED."""
    exp = _near_exp(3)
    return [
        {
            "symbol": "SPY",
            "expiration": exp,
            "strike": 500.0,
            "option_type": "call",
            "bid": None,
            "ask": None,
            "delta": 0.61,
            "vwap": 5.1,
            "dte": 3,
            "open_interest": 1001.0,
            "underlying_price": None,
        },
        {
            # in-window CV-only contract: never enters the result
            "symbol": "SPY",
            "expiration": _near_exp(4),
            "strike": 502.0,
            "option_type": "call",
            "bid": 2.0,
            "ask": 2.5,
            "delta": 0.1,
            "vwap": 2.2,
            "dte": 4,
            "open_interest": 5000.0,
            "underlying_price": 501.0,
        },
    ]


def _patch_chain(
    monkeypatch: pytest.MonkeyPatch,
    *,
    schwab_records: list[dict] | None = None,
    contract_count: int = 120,
    cv_records: list[dict] | None = None,
    cv_enabled: bool = True,
    schwab_enabled: bool = True,
    schwab_error: Exception | None = None,
    cv_error: Exception | None = None,
) -> dict:
    """Wire fakes into _fetch_options_chain_with_enrichment / _options_chain_execute."""
    import openbb_agent_cli.executors as executors_module
    import openbb_finance.registry as registry_module
    from openbb_finance.models.equity_options_chain import FinanceOptionsChainFetcher

    calls: dict = {"cv_requests": 0}

    class FakeRegistry:
        def __init__(self):
            self._schwab = SimpleNamespace(
                name="schwab",
                enabled=schwab_enabled,
                fetch_options_chain=self._fetch_schwab_chain,
            )

        async def _fetch_schwab_chain(self, symbol, **kwargs):
            calls["schwab"] = {"symbol": symbol, **kwargs}
            if schwab_error is not None:
                raise schwab_error
            return {"records": list(schwab_records or []), "contract_count": contract_count}

        def get(self, name):
            return self._schwab if name == "schwab" else None

    async def fake_aextract(query, credentials, **kwargs):
        calls["cv_requests"] += 1
        if cv_error is not None:
            raise cv_error
        return {"records": list(cv_records or []), "contract_count": 99999}

    monkeypatch.setattr(registry_module, "build_default_registry", FakeRegistry)
    monkeypatch.setattr(FinanceOptionsChainFetcher, "aextract_data", fake_aextract)
    monkeypatch.setattr(executors_module, "_cv_api_key", lambda: "k" if cv_enabled else "")
    return calls


def test_chain_schwab_anchors_keys_and_cv_only_fills_missing_fields(monkeypatch: pytest.MonkeyPatch):
    from openbb_agent_cli.executors import _options_chain_execute

    calls = _patch_chain(
        monkeypatch,
        schwab_records=_schwab_chain_rows(),
        contract_count=120,
        cv_records=_cv_chain_rows(),
    )

    records, meta = _options_chain_execute(
        {
            "symbol": "SPY",
            "dte_min": 0,
            "dte_max": 45,
            "atm": 20,
            "sort_by": "open_interest",
            "sort_dir": "desc",
            "limit": 0,
        }
    )

    exp = _near_exp(3)
    by_key = {(r["expiration"], r["strike"], r["option_type"]): r for r in records}
    # The result key set is a subset of the Schwab keys: the in-window CV-only
    # contract (exp+4, strike 502) never survives.
    assert set(by_key) == {
        (exp, 500.0, "call"),
        (exp, 505.0, "call"),
    }

    matched = by_key[(exp, 500.0, "call")]
    # CV bid/ask are null on the matched row, but Schwab values stay untouched.
    assert matched["bid"] == 5.0
    assert matched["ask"] == 5.3
    # Both sides populated -> Schwab keeps delta/OI.
    assert matched["delta"] == 0.6
    assert matched["open_interest"] == 1000.0
    # Schwab left vwap null -> CV fills it.
    assert matched["vwap"] == 5.1
    # Upstream dte was poisoned (999) -> recomputed from expiration/as_of.
    assert matched["dte"] == 3

    # The Schwab request pushed down the absolute window and raw atm (no dte).
    assert calls["schwab"]["from_date"] == datetime.now(timezone.utc).date()
    assert calls["schwab"]["to_date"] == datetime.now(timezone.utc).date() + timedelta(days=45)
    assert calls["schwab"]["strike_count"] == 20
    assert "dte" not in calls["schwab"]

    # total comes from Schwab; CV's huge full-chain count is irrelevant.
    assert meta["total"] == 120
    assert meta["sources_used"] == ["schwab", "convexvalue"]
    assert meta["cv_enrichment"] == "success"
    assert meta["atm_reference_price"] == 501.0
    assert meta["window"]["mode"] == "dte"
    assert meta["window"]["dte_min"] == 0
    assert meta["window"]["dte_max"] == 45
    assert meta["window"]["span"] == 45
    assert meta["atm"] == 20


def test_chain_cv_failure_keeps_schwab_rows_and_reports_failed(monkeypatch: pytest.MonkeyPatch):
    from openbb_agent_cli.executors import _options_chain_execute

    _patch_chain(
        monkeypatch,
        schwab_records=_schwab_chain_rows(),
        contract_count=2,
        cv_records=_cv_chain_rows(),
        cv_error=RuntimeError("CV down"),
    )

    records, meta = _options_chain_execute({"symbol": "SPY", "limit": 0})

    assert len(records) == 2
    assert all(record.get("vwap") is None for record in records)  # untouched Schwab rows
    assert meta["sources_used"] == ["schwab"]
    assert meta["cv_enrichment"] == "failed"
    assert meta["total"] == 2


def test_chain_schwab_disabled_fails_without_cv_requests(monkeypatch: pytest.MonkeyPatch):
    from openbb_agent_cli.executors import _options_chain_execute
    from openbb_finance.sources.base import SourceError

    calls = _patch_chain(
        monkeypatch,
        schwab_records=_schwab_chain_rows(),
        cv_records=_cv_chain_rows(),
        schwab_enabled=False,
    )

    with pytest.raises(SourceError, match="schwab source is required"):
        _options_chain_execute({"symbol": "SPY", "limit": 0})

    assert "schwab" not in calls
    assert calls["cv_requests"] == 0


def test_chain_schwab_request_error_propagates_without_cv_requests(monkeypatch: pytest.MonkeyPatch):
    from openbb_agent_cli.executors import _options_chain_execute
    from openbb_finance.sources.base import SourceError

    calls = _patch_chain(
        monkeypatch,
        schwab_records=_schwab_chain_rows(),
        cv_records=_cv_chain_rows(),
        schwab_error=SourceError("schwab-api unreachable"),
    )

    with pytest.raises(SourceError, match="schwab-api unreachable"):
        _options_chain_execute({"symbol": "SPY", "limit": 0})

    assert calls["cv_requests"] == 0


def test_chain_empty_schwab_chain_succeeds_and_skips_cv(monkeypatch: pytest.MonkeyPatch):
    from openbb_agent_cli.executors import _options_chain_execute

    calls = _patch_chain(
        monkeypatch,
        schwab_records=[],
        contract_count=0,
        cv_records=_cv_chain_rows(),
    )

    records, meta = _options_chain_execute({"symbol": "SPY", "limit": 0})

    assert records == []
    assert meta["total"] == 0
    assert meta["cv_enrichment"] == "skipped_empty"
    assert meta["sources_used"] == ["schwab"]
    assert calls["cv_requests"] == 0


def test_chain_local_date_filter_drops_out_of_window_rows(monkeypatch: pytest.MonkeyPatch):
    """Schwab's server-side window filter is loose; rows outside the resolved
    absolute window are dropped locally, and a fully-filtered-out chain is an
    EMPTY SUCCESS (not an error) that skips CV."""
    from openbb_agent_cli.executors import _options_chain_execute

    far = _near_exp(400)
    out_of_window = [
        {
            "symbol": "SPY",
            "expiration": far,
            "strike": 400.0,
            "option_type": "call",
            "dte": 400,
            "underlying_price": 501.0,
            "open_interest": 99999.0,
        },
    ]
    _patch_chain(
        monkeypatch,
        schwab_records=_schwab_chain_rows() + out_of_window,
        contract_count=3,
        cv_records=_cv_chain_rows(),
    )

    records, meta = _options_chain_execute({"symbol": "SPY", "dte_min": 0, "dte_max": 45, "limit": 0})

    assert [record["expiration"] for record in records] == [_near_exp(3)] * 2
    assert meta["total"] == 3  # Schwab's own count, pre-filter

    only_far = _patch_chain(
        monkeypatch,
        schwab_records=out_of_window,
        contract_count=1,
        cv_records=_cv_chain_rows(),
    )
    records, meta = _options_chain_execute({"symbol": "SPY", "dte_min": 0, "dte_max": 45, "limit": 0})
    assert records == []
    assert meta["cv_enrichment"] == "skipped_empty"
    assert only_far["cv_requests"] == 0


def test_chain_expiration_mode_pushes_single_day_window(monkeypatch: pytest.MonkeyPatch):
    from openbb_agent_cli.executors import _options_chain_execute

    exp = _near_exp(3)
    calls = _patch_chain(
        monkeypatch,
        schwab_records=_schwab_chain_rows(),
        contract_count=120,
        cv_records=_cv_chain_rows(),
        cv_enabled=False,
    )

    records, meta = _options_chain_execute({"symbol": "SPY", "expiration": exp.isoformat(), "limit": 0})

    assert calls["schwab"]["from_date"] == exp
    assert calls["schwab"]["to_date"] == exp
    assert meta["window"]["mode"] == "expiration"
    assert meta["window"]["expiration"] == exp.isoformat()
    assert meta["window"]["span"] == 0
    assert meta["sources_used"] == ["schwab"]
    assert meta["cv_enrichment"] == "disabled"
    assert len(records) == 2


def test_chain_missing_reference_price_raises_integrity_error(monkeypatch: pytest.MonkeyPatch):
    from openbb_agent_cli.executors import _options_chain_execute
    from openbb_finance.sources.base import SourceError

    rows = [{**row, "underlying_price": None} for row in _schwab_chain_rows()]
    _patch_chain(
        monkeypatch,
        schwab_records=rows,
        contract_count=2,
        cv_records=[],
        cv_enabled=False,
    )

    with pytest.raises(SourceError, match="underlying_price"):
        _options_chain_execute({"symbol": "SPY", "limit": 0})


def test_chain_reference_price_falls_back_to_cv_enrichment(monkeypatch: pytest.MonkeyPatch):
    from openbb_agent_cli.executors import _options_chain_execute

    exp = _near_exp(3)
    rows = [{**row, "underlying_price": None} for row in _schwab_chain_rows()]
    cv_rows = [
        {
            "symbol": "SPY",
            "expiration": exp,
            "strike": 500.0,
            "option_type": "call",
            "underlying_price": 503.0,
        },
    ]
    _patch_chain(
        monkeypatch,
        schwab_records=rows,
        contract_count=2,
        cv_records=cv_rows,
    )

    _records, meta = _options_chain_execute({"symbol": "SPY", "limit": 0})

    # Schwab has no price; the matched CV fill provides the reference.
    assert meta["atm_reference_price"] == 503.0


def test_chain_atm_selects_shared_nearest_strikes_per_expiration(monkeypatch: pytest.MonkeyPatch):
    from openbb_agent_cli.executors import _options_chain_execute

    exp = _near_exp(3)
    # Strikes 400/450/500/501/600 around reference 500, both sides at 500/501.
    rows = []
    for strike in (400.0, 450.0, 500.0, 501.0, 600.0):
        for option_type in ("call", "put"):
            rows.append(
                {
                    "symbol": "SPY",
                    "expiration": exp,
                    "strike": strike,
                    "option_type": option_type,
                    "underlying_price": 500.5,
                    "open_interest": strike,
                }
            )
    # Tie case: 500 and 501 are equidistant from 500.5; the LOWER strike wins.
    _patch_chain(monkeypatch, schwab_records=rows, contract_count=10, cv_enabled=False)

    records, _meta = _options_chain_execute({"symbol": "SPY", "atm": 2, "limit": 0})

    kept = {(record["strike"], record["option_type"]) for record in records}
    assert kept == {(500.0, "call"), (500.0, "put"), (501.0, "call"), (501.0, "put")}


def test_chain_option_type_filter_applies_after_atm(monkeypatch: pytest.MonkeyPatch):
    from openbb_agent_cli.executors import _options_chain_execute

    exp = _near_exp(3)
    rows = []
    for strike in (500.0, 501.0):
        for option_type in ("call", "put"):
            rows.append(
                {
                    "symbol": "SPY",
                    "expiration": exp,
                    "strike": strike,
                    "option_type": option_type,
                    "underlying_price": 500.5,
                }
            )
    _patch_chain(monkeypatch, schwab_records=rows, contract_count=4, cv_enabled=False)

    records, meta = _options_chain_execute({"symbol": "SPY", "atm": 2, "option_type": "put", "limit": 0})

    assert {(record["strike"], record["option_type"]) for record in records} == {
        (500.0, "put"),
        (501.0, "put"),
    }
    assert meta["filtered"] == 2
    assert meta["returned"] == 2


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


async def test_fetch_options_chain_date_window_mode_pushes_absolute_dates():
    source = FakeChainSchwab()

    data = await source.fetch_options_chain(
        "AAPL", from_date=date(2026, 9, 9), to_date=date(2026, 11, 23), strike_count=20
    )

    assert source.calls == [
        (
            "/api/v1/options/chains",
            {
                "symbol": "AAPL",
                "from_date": "2026-09-09",
                "to_date": "2026-11-23",
                "strike_count": 20,
            },
        )
    ]
    assert data["contract_count"] == 4


async def test_fetch_options_chain_date_mode_rejects_legacy_contract():
    source = FakeChainSchwab()

    with pytest.raises(SourceError, match="mutually exclusive"):
        await source.fetch_options_chain(
            "AAPL", dte=10, from_date=date(2026, 9, 9), to_date=date(2026, 9, 9), strike_count=20
        )
    with pytest.raises(SourceError, match="from_date and to_date"):
        await source.fetch_options_chain("AAPL", from_date=date(2026, 9, 9), strike_count=20)
    with pytest.raises(SourceError, match="positive strike_count"):
        await source.fetch_options_chain("AAPL", from_date=date(2026, 9, 9), to_date=date(2026, 9, 9), strike_count=0)
    with pytest.raises(SourceError, match="range_/strategy"):
        await source.fetch_options_chain(
            "AAPL", from_date=date(2026, 9, 9), to_date=date(2026, 9, 9), strike_count=20, range_="ITM"
        )


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
