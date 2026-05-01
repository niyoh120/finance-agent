from __future__ import annotations

import sys
from typing import Any

import pytest
from openbb_agent_cli import cli


class DummyResult:
    def model_dump(self, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return {"results": [{"symbol": "AAPL"}]}


def test_run_route_outputs_results_only(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def command(provider: str, **params: Any) -> DummyResult:
        assert provider == "finance"
        assert params == {"query": "AAPL", "is_symbol": False}
        return DummyResult()

    monkeypatch.setattr(cli, "_resolve_route", lambda route: command)

    cli._run_route("equity.search", query="AAPL", is_symbol=False, start_date=None)

    assert capsys.readouterr().out == '[{"symbol":"AAPL"}]\n'


def test_run_route_suppresses_provider_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def command(provider: str, **params: Any) -> DummyResult:
        print("provider stdout")
        print("provider stderr", file=sys.stderr)
        return DummyResult()

    monkeypatch.setattr(cli, "_resolve_route", lambda route: command)

    cli._run_route("equity.search")

    captured = capsys.readouterr()
    assert captured.out == '[{"symbol":"AAPL"}]\n'
    assert captured.err == ""


def test_run_route_outputs_json_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def command(provider: str, **params: Any) -> DummyResult:
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "_resolve_route", lambda route: command)

    with pytest.raises(SystemExit) as exc_info:
        cli._run_route("equity.search")

    assert exc_info.value.code == 1
    assert capsys.readouterr().out == '{"error":"boom","code":"RUNTIMEERROR"}\n'


def test_index_snapshots_coerces_single_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def run_provider_model(
        model_name: str,
        standard_params: dict[str, Any] | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> None:
        captured["model_name"] = model_name
        captured["standard_params"] = standard_params
        captured["extra_params"] = extra_params

    monkeypatch.setattr(cli, "_run_provider_model", run_provider_model)

    cli.index_snapshots(symbol="000001.XSHG")  # type: ignore[arg-type]

    assert captured == {
        "model_name": "IndexSnapshots",
        "standard_params": {"region": "cn"},
        "extra_params": {"symbol": ["000001.XSHG"]},
    }


def test_equity_screener_uses_run_route(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def run_route(route: str, **params: Any) -> None:
        captured["route"] = route
        captured["params"] = params

    monkeypatch.setattr(cli, "_run_route", run_route)

    cli.equity_screener(
        market="america",
        limit=50,
        price_min=50.0,
        price_max=200.0,
        change_percent_min=5.0,
        volume_min=1000000,
        sector=["Technology"],
    )

    assert captured["route"] == "equity.screener"
    assert captured["params"]["market"] == "america"
    assert captured["params"]["limit"] == 50
    assert captured["params"]["price_min"] == 50.0
    assert captured["params"]["price_max"] == 200.0
    assert captured["params"]["change_percent_min"] == 5.0
    assert captured["params"]["volume_min"] == 1000000
    assert captured["params"]["sector"] == ["Technology"]


def test_equity_screener_with_rsi_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def run_route(route: str, **params: Any) -> None:
        captured["route"] = route
        captured["params"] = params

    monkeypatch.setattr(cli, "_run_route", run_route)

    cli.equity_screener(market="hongkong", rsi_max=30)

    assert captured["route"] == "equity.screener"
    assert captured["params"]["market"] == "hongkong"
    assert captured["params"]["rsi_max"] == 30
