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
