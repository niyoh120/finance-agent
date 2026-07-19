"""AppTest smoke tests for the chain + strategy page.

Validates:
- Empty-state prompt before a symbol is submitted.
- Chain control bar + table render once a symbol is set.
- Selecting a chain row auto-adds a leg (no 加入策略 button).
- Strategy table is editable (方向 / 张数 / 建仓价 / IV).
- Valuation parameters have independent restore buttons.
- Contract symbols render trader-friendly (AAPL 260918 100C).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

streamlit = pytest.importorskip("streamlit")
AppTest = pytest.importorskip("streamlit.testing.v1").AppTest  # type: ignore[attr-defined]

import options_dashboard.data as data_mod  # noqa: E402
from options_dashboard.pages.market import fmt_contract  # noqa: E402
from options_dashboard.state import STRATEGY_LEGS_KEY  # noqa: E402


@pytest.fixture(autouse=True)
def _mock_upstreams(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_mod, "fetch_option_chain_sync", _fake_chain)
    monkeypatch.setattr(data_mod, "fetch_equity_quote_sync", _fake_quote)
    monkeypatch.setattr(data_mod, "fetch_profile_sync", _fake_profile)
    monkeypatch.setattr(data_mod, "fetch_treasury_rates_sync", _fake_treasury)
    monkeypatch.setattr(data_mod, "fetch_earnings_sync", _fake_earnings)
    monkeypatch.setattr(data_mod, "fetch_option_daily_sync", _fake_option_daily)
    monkeypatch.setattr(data_mod, "fetch_equity_eod_sync", _fake_equity_eod)


def _fake_chain(symbol: str) -> list[dict[str, Any]]:
    rows = []
    for side in ("call", "put"):
        for strike in (100.0, 105.0):
            rows.append({
                "contract_symbol": f"O:{symbol}260918{side[0].upper()}{int(strike*1000):08d}",
                "option_type": side,
                "strike": strike, "expiration": "2026-09-18", "dte": 66,
                "implied_volatility": 0.30, "delta": 0.50 if side == "call" else -0.50,
                "gamma": 0.01, "theta": -0.02, "vega": 0.1, "mark": 5.1,
                "theoretical_price": 5.0, "open_interest": 1000, "volume": 10,
                "underlying_price": 100.0,
            })
    return rows


def _fake_quote(symbol: str) -> dict[str, Any]:
    return {"last_price": 101.0}


def _fake_profile(symbol: str) -> dict[str, Any]:
    return {"price": 101.0, "lastDividend": 1.0}


def _fake_treasury(limit: int = 10) -> list[dict[str, Any]]:
    return [{"date": "2026-07-10", "month3": 4.0, "month6": 4.2}]


def _fake_earnings(symbol: str, limit: int = 8) -> list[dict[str, Any]]:
    return [
        {"date": "2026-02-10"},
        {"date": "2026-03-10"},
        {"date": "2026-04-10"},
        {"date": "2026-05-10"},
        {"date": "2026-08-10"},
    ]


def _fake_option_daily(contract: str, as_of: str) -> dict[str, Any]:
    return {"close": 5.0}


def _fake_equity_eod(symbol: str, start: str, end: str) -> list[dict[str, Any]]:
    if start == end:
        return [{"date": start, "close": 100.0}]
    return [{"date": start, "close": 100.0}, {"date": end, "close": 101.0}]


# ---------- contract symbol formatting ----------

def test_fmt_contract_trader_friendly() -> None:
    assert fmt_contract("O:AAPL260918C00100000") == "AAPL 260918 100C"
    assert fmt_contract("O:NVDA260717P00450000") == "NVDA 260717 450P"
    assert fmt_contract("O:SPY260117C00450500") == "SPY 260117 450.5C"
    assert fmt_contract("garbage") == "garbage"
    assert fmt_contract("") == ""


# ---------- auto-refresh fmv update ----------

class _FakeSessionState(dict):
    """Minimal stand-in for st.session_state used by _refresh_leg_fmvs."""


def test_refresh_leg_fmvs_updates_changed_fmv(monkeypatch: pytest.MonkeyPatch) -> None:
    """_refresh_leg_fmvs rewrites fmv when the chain snapshot changed."""
    from options_dashboard.pages import market as market_mod

    legs = [{
        "kind": "option", "direction": "buy", "quantity": 1.0,
        "kind_symbol": "O:AAPL260918C00100000",
        "iv": 0.30, "fmv": 5.0,  # user-set iv preserved; fmv refreshed
    }]
    monkeypatch.setattr(streamlit, "session_state", _FakeSessionState({STRATEGY_LEGS_KEY: legs}))

    records = [{
        "contract_symbol": "O:AAPL260918C00100000",
        "theoretical_price": 6.25,
    }]
    changed = market_mod._refresh_leg_fmvs(records)

    assert changed is True
    assert legs[0]["fmv"] == 6.25
    assert legs[0]["iv"] == 0.30  # user-set value untouched


def test_refresh_leg_fmvs_noop_when_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """_refresh_leg_fmvs returns False and does not write state when unchanged."""
    from options_dashboard.pages import market as market_mod

    legs = [{
        "kind": "option", "direction": "buy", "quantity": 1.0,
        "kind_symbol": "O:AAPL260918C00100000", "fmv": 5.0,
    }]
    fake_state = _FakeSessionState({STRATEGY_LEGS_KEY: legs})
    monkeypatch.setattr(streamlit, "session_state", fake_state)

    legs_before = [dict(legs[0])]
    changed = market_mod._refresh_leg_fmvs([
        {"contract_symbol": "O:AAPL260918C00100000", "theoretical_price": 5.0},
    ])
    assert changed is False
    assert legs == legs_before  # untouched



def test_refresh_leg_fmvs_skips_malformed_price(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-numeric theoretical_price is skipped, not raised."""
    from options_dashboard.pages import market as market_mod

    legs = [{
        "kind": "option", "direction": "buy", "quantity": 1.0,
        "kind_symbol": "O:AAPL260918C00100000", "fmv": 5.0,
    }]
    monkeypatch.setattr(streamlit, "session_state", _FakeSessionState({STRATEGY_LEGS_KEY: legs}))

    changed = market_mod._refresh_leg_fmvs([
        {"contract_symbol": "O:AAPL260918C00100000", "theoretical_price": "N/A"},
    ])
    assert changed is False
    assert legs[0]["fmv"] == 5.0


def test_refresh_leg_fmvs_clears_stale_fmv_on_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """When CV reports 0/None, a stale positive fmv is cleared to None (shows —)."""
    from options_dashboard.pages import market as market_mod

    legs = [{
        "kind": "option", "direction": "buy", "quantity": 1.0,
        "kind_symbol": "O:AAPL260918C00100000", "fmv": 5.0,
    }]
    monkeypatch.setattr(streamlit, "session_state", _FakeSessionState({STRATEGY_LEGS_KEY: legs}))

    changed = market_mod._refresh_leg_fmvs([
        {"contract_symbol": "O:AAPL260918C00100000", "theoretical_price": 0},
    ])
    assert changed is True
    assert legs[0]["fmv"] is None


# ---------- page render flows ----------

def test_page_prompts_before_symbol_submit() -> None:
    at = AppTest.from_file("services/options-dashboard/app.py", default_timeout=30).run()
    assert not at.exception
    assert any("输入标的" in i.value for i in at.info)


def test_page_renders_chain_when_symbol_set() -> None:
    at = AppTest.from_file("services/options-dashboard/app.py", default_timeout=30)
    at.session_state["od_symbol"] = "AAPL"
    at = at.run()
    assert not at.exception
    # Chain renders as per-row columns with “加入” buttons (no dataframe selection).
    add_btns = [b for b in at.button if b.label == "+"]
    assert len(add_btns) >= 2  # at least 2 contracts (100, 105 strikes * call/put)


def test_clicking_add_button_adds_leg() -> None:
    """Clicking a 加入 button on a chain row adds a leg."""
    at = AppTest.from_file("services/options-dashboard/app.py", default_timeout=30)
    at.session_state["od_symbol"] = "AAPL"
    at = at.run()
    assert not at.exception
    add_btns = [b for b in at.button if b.label == "+"]
    assert add_btns
    add_btns[0].click()  # first contract (call @ 100)
    at = at.run()
    legs = at.session_state[STRATEGY_LEGS_KEY]
    assert len(legs) == 1
    assert legs[0]["option_side"] == "call"
    assert legs[0]["strike"] == 100.0


def test_strategy_table_is_editable() -> None:
    """Strategy section shows each leg as an editable card with a remove button."""
    at = AppTest.from_file("services/options-dashboard/app.py", default_timeout=30)
    at.session_state["od_symbol"] = "AAPL"
    at.session_state[STRATEGY_LEGS_KEY] = [
        {"kind": "option", "direction": "buy", "quantity": 1.0,
         "kind_symbol": "O:AAPL260918C00100000", "underlying": "AAPL",
         "strike": 100.0, "expiration": "2026-09-18", "option_side": "call",
         "style": "american", "iv": 0.3, "cost": 5.0,
         "iv_default": 0.3, "cost_default": 5.0},
        {"kind": "option", "direction": "sell", "quantity": 1.0,
         "kind_symbol": "O:AAPL260918C00105000", "underlying": "AAPL",
         "strike": 105.0, "expiration": "2026-09-18", "option_side": "call",
         "style": "american", "iv": 0.28, "cost": 2.0,
         "iv_default": 0.28, "cost_default": 2.0},
    ]
    at = at.run()
    assert not at.exception
    # Two compact remove buttons (one per leg).
    delete_btns = [b for b in at.button if b.label == "×"]
    assert len(delete_btns) == 2
    # Net valuation metrics render (2 metrics: 净理论价/净FMV).
    assert len(at.metric) >= 2
    # Delete the first leg.
    delete_btns[0].click()
    at = at.run()
    legs = at.session_state[STRATEGY_LEGS_KEY]
    assert len(legs) == 1
    assert legs[0]["strike"] == 105.0  # second leg remains


def test_earnings_crush_panel_shows_strategy_price_difference() -> None:
    """Post-earnings valuation shows before/after strategy model prices."""
    at = AppTest.from_file("services/options-dashboard/app.py", default_timeout=30)
    at.session_state["od_symbol"] = "AAPL"
    at.session_state["ctx_val_date"] = date(2026, 8, 11)
    at.session_state[STRATEGY_LEGS_KEY] = [
        {"kind": "option", "direction": "buy", "quantity": 1.0,
         "kind_symbol": "O:AAPL260918C00100000", "underlying": "AAPL",
         "strike": 100.0, "expiration": "2026-09-18", "option_side": "call",
         "style": "american", "iv": 0.3, "cost": 5.0,
         "iv_default": 0.3, "cost_default": 5.0, "fmv": 5.0},
    ]
    at = at.run()
    assert not at.exception
    analyze = next(b for b in at.button if b.key == "earnings_analyze_AAPL")
    analyze.click()
    at = at.run()
    metric_labels = {metric.label for metric in at.metric}
    assert {"财报前组合模型价", "财报后组合模型价", "财报前后差额"} <= metric_labels


def test_market_params_independent_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each market param has its own reset button; overriding spot doesn't reset r."""
    at = AppTest.from_file("services/options-dashboard/app.py", default_timeout=30)
    at.session_state["od_symbol"] = "AAPL"
    at = at.run()
    assert not at.exception
    defaults = at.session_state["_ctx_defaults"]
    assert defaults["spot"] == 101.0

    # Override spot and r, then reset only spot from the latest quote.
    spot_input = next(n for n in at.number_input if n.label == "标的价格")
    spot_input.set_value(150.0)
    r_input = next(n for n in at.number_input if n.label == "无风险利率")
    r_input.set_value(0.10)
    at = at.run()
    assert at.session_state["ctx_spot"] == 150.0
    assert at.session_state["ctx_r"] == 0.10

    # The reset callback requests a new quote instead of restoring the first
    # page-load default.
    monkeypatch.setattr(data_mod, "fetch_equity_quote_sync", lambda _: {"last_price": 123.45})
    reset_spot = next(b for b in at.button if b.key == "ctx_reset_spot")
    reset_spot.click()
    at = at.run()
    assert at.session_state["ctx_spot"] == 123.45
    assert at.session_state["ctx_r"] == 0.10  # unchanged
