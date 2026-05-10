from __future__ import annotations

import json
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
        fields='["SYMBOL","NAME","PRICE"]',
    )

    assert captured["route"] == "equity.screener"
    assert captured["params"]["market"] == "america"
    assert captured["params"]["limit"] == 50
    assert captured["params"]["price_min"] == 50.0
    assert captured["params"]["price_max"] == 200.0
    assert captured["params"]["change_percent_min"] == 5.0
    assert captured["params"]["volume_min"] == 1000000
    assert captured["params"]["sector"] == ["Technology"]
    assert captured["params"]["fields"] == '["SYMBOL","NAME","PRICE"]'


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


def test_economy_available_indicators_uses_run_route(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def run_route(route: str, **params: Any) -> None:
        captured["route"] = route
        captured["params"] = params

    monkeypatch.setattr(cli, "_run_route", run_route)

    cli.economy_available_indicators()

    assert captured == {"route": "economy.available_indicators", "params": {}}


def test_economy_indicators_uses_run_route(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def run_route(route: str, **params: Any) -> None:
        captured["route"] = route
        captured["params"] = params

    monkeypatch.setattr(cli, "_run_route", run_route)

    cli.economy_indicators(
        symbol="PMI",
        country="china",
        frequency="month",
        start_date="2026-01-01",
        end_date="2026-03-31",
    )

    assert captured == {
        "route": "economy.indicators",
        "params": {
            "symbol": "PMI",
            "country": "china",
            "frequency": "month",
            "start_date": "2026-01-01",
            "end_date": "2026-03-31",
        },
    }


def test_economy_gdp_nominal_uses_run_route(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def run_route(route: str, **params: Any) -> None:
        captured["route"] = route
        captured["params"] = params

    monkeypatch.setattr(cli, "_run_route", run_route)

    cli.economy_gdp_nominal(country="CN", start_date="2025-01-01")

    assert captured == {
        "route": "economy.gdp.nominal",
        "params": {
            "country": "CN",
            "start_date": "2025-01-01",
            "end_date": None,
        },
    }


def test_economy_cpi_uses_run_route(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def run_route(route: str, **params: Any) -> None:
        captured["route"] = route
        captured["params"] = params

    monkeypatch.setattr(cli, "_run_route", run_route)

    cli.economy_cpi(
        country="china",
        transform="yoy",
        frequency="quarter",
        harmonized=True,
        start_date="2025-01-01",
        end_date="2025-12-31",
    )

    assert captured == {
        "route": "economy.cpi",
        "params": {
            "country": "china",
            "transform": "yoy",
            "frequency": "quarter",
            "harmonized": True,
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
        },
    }


def test_run_batch_queries_collects_results_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def quote_executor(params: dict[str, Any]) -> list[dict[str, Any]]:
        assert params == {"symbol": "AAPL"}
        return [{"symbol": "AAPL", "price": 100}]

    def failing_executor(params: dict[str, Any]) -> list[dict[str, Any]]:
        raise RuntimeError("boom")

    monkeypatch.setitem(cli.COMMAND_EXECUTORS, "test.quote", quote_executor)
    monkeypatch.setitem(cli.COMMAND_EXECUTORS, "test.fail", failing_executor)

    payload = cli._run_batch_queries(
        [
            {"name": "quote", "command": "test.quote", "params": {"symbol": "AAPL"}},
            {"name": "failed", "command": "test.fail"},
        ],
        max_workers=2,
    )

    assert payload == {
        "results": {"quote": [{"symbol": "AAPL", "price": 100}]},
        "errors": {"failed": {"error": "boom", "code": "RUNTIMEERROR"}},
    }


def test_run_batch_queries_executes_serially(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    def first_executor(params: dict[str, Any]) -> list[dict[str, Any]]:
        events.append("first")
        return []

    def second_executor(params: dict[str, Any]) -> list[dict[str, Any]]:
        events.append("second")
        return []

    monkeypatch.setitem(cli.COMMAND_EXECUTORS, "test.first", first_executor)
    monkeypatch.setitem(cli.COMMAND_EXECUTORS, "test.second", second_executor)

    cli._run_batch_queries(
        [
            {"name": "first", "command": "test.first"},
            {"name": "second", "command": "test.second"},
        ],
        max_workers=2,
    )

    assert events == ["first", "second"]


def test_run_batch_queries_preserves_repeated_unnamed_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        cli.COMMAND_EXECUTORS,
        "test.quote",
        lambda params: [{"symbol": params["symbol"]}],
    )

    payload = cli._run_batch_queries(
        [
            {"command": "test.quote", "params": {"symbol": "AAPL"}},
            {"command": "test.quote", "params": {"symbol": "MSFT"}},
        ],
        max_workers=2,
    )

    assert payload == {
        "results": {
            "0": [{"symbol": "AAPL"}],
            "1": [{"symbol": "MSFT"}],
        },
        "errors": {},
    }


def test_batch_outputs_json_payload(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setitem(
        cli.COMMAND_EXECUTORS,
        "test.quote",
        lambda params: [{"symbol": params["symbol"]}],
    )

    cli.batch(queries='[{"name":"quote","command":"test.quote","params":{"symbol":"AAPL"}}]')

    assert json.loads(capsys.readouterr().out) == {
        "results": {"quote": [{"symbol": "AAPL"}]},
        "errors": {},
    }


def test_equity_overview_template_builds_expected_queries() -> None:
    queries = cli._build_template_queries(
        "equity-overview",
        {
            "symbol": "AAPL",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "news_limit": 5,
            "options_limit": 6,
        },
    )

    assert [query["name"] for query in queries] == ["quote", "historical", "news", "options"]
    assert queries[0] == {
        "name": "quote",
        "command": "equity.price.quote",
        "params": {"symbol": "AAPL"},
    }
    assert queries[2]["params"] == {
        "symbol": "AAPL",
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "limit": 5,
    }
    assert queries[3]["params"]["limit"] == 6


def test_batch_template_requires_symbol(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.batch(template="equity-overview")

    assert exc_info.value.code == 1
    assert json.loads(capsys.readouterr().out) == {
        "error": "template equity-overview requires symbol",
        "code": "VALUEERROR",
    }


def test_apply_limit_returns_last_n_items() -> None:
    data = [{"i": 1}, {"i": 2}, {"i": 3}, {"i": 4}, {"i": 5}]
    assert cli._apply_limit(data, 3) == [{"i": 3}, {"i": 4}, {"i": 5}]


def test_apply_limit_none_returns_all() -> None:
    data = [{"i": 1}, {"i": 2}, {"i": 3}]
    assert cli._apply_limit(data, None) is data


def test_apply_limit_zero_raises() -> None:
    with pytest.raises(ValueError, match="limit must be >= 1"):
        cli._apply_limit([{"i": 1}], 0)


def test_apply_limit_negative_raises() -> None:
    with pytest.raises(ValueError, match="limit must be >= 1"):
        cli._apply_limit([{"i": 1}], -1)


def test_apply_limit_larger_than_data_returns_all() -> None:
    data = [{"i": 1}, {"i": 2}]
    assert cli._apply_limit(data, 100) == data


def test_historical_executor_applies_limit() -> None:
    called_with: dict[str, Any] = {}

    def fake_execute_route(route: str, **params: Any) -> list[dict[str, Any]]:
        called_with.update({"route": route, **params})
        return [{"symbol": "AAPL", "i": i} for i in range(10)]

    monkeypatch_local = pytest.MonkeyPatch()
    monkeypatch_local.setattr(cli, "_execute_route", fake_execute_route)

    executor = cli._historical_executor("index.price.historical")
    params = {"symbol": "000001.XSHG", "start_date": "2026-01-01", "end_date": "2026-01-31", "__cli_limit__": 3}
    result = executor(params)

    assert len(result) == 3
    assert result[0]["i"] == 7
    assert result[1]["i"] == 8
    assert result[2]["i"] == 9
    assert called_with["symbol"] == "000001.XSHG"
    assert "__cli_limit__" not in called_with

    monkeypatch_local.undo()


def test_historical_executor_no_limit_returns_all() -> None:
    def fake_execute_route(route: str, **params: Any) -> list[dict[str, Any]]:
        return [{"symbol": "AAPL", "i": i} for i in range(5)]

    monkeypatch_local = pytest.MonkeyPatch()
    monkeypatch_local.setattr(cli, "_execute_route", fake_execute_route)

    executor = cli._historical_executor("etf.historical")
    result = executor({"symbol": "510300.XSHG"})

    assert len(result) == 5

    monkeypatch_local.undo()


def test_equity_price_historical_passes_limit(capsys: pytest.CaptureFixture[str]) -> None:
    called_with: dict[str, Any] = {}

    def fake_execute_route(route: str, **params: Any) -> list[dict[str, Any]]:
        called_with.update({"route": route, **params})
        return [{"symbol": "AAPL", "i": i} for i in range(10)]

    monkeypatch_local = pytest.MonkeyPatch()
    monkeypatch_local.setattr(cli, "_execute_route", fake_execute_route)

    cli.equity_price_historical(symbol="AAPL", start_date="2026-01-01", end_date="2026-01-31", limit=5)

    output = json.loads(capsys.readouterr().out)
    assert len(output) == 5
    assert called_with["route"] == "equity.price.historical"
    assert called_with.get("limit") is None

    monkeypatch_local.undo()


def test_index_price_historical_passes_limit(capsys: pytest.CaptureFixture[str]) -> None:
    def fake_execute_route(route: str, **params: Any) -> list[dict[str, Any]]:
        return [{"symbol": "000001.XSHG", "i": i} for i in range(8)]

    monkeypatch_local = pytest.MonkeyPatch()
    monkeypatch_local.setattr(cli, "_execute_route", fake_execute_route)

    cli.index_price_historical(symbol="000001.XSHG", limit=3)

    output = json.loads(capsys.readouterr().out)
    assert len(output) == 3
    assert output[0]["i"] == 5

    monkeypatch_local.undo()


def test_etf_historical_passes_limit(capsys: pytest.CaptureFixture[str]) -> None:
    def fake_execute_route(route: str, **params: Any) -> list[dict[str, Any]]:
        return [{"symbol": "510300.XSHG", "i": i} for i in range(6)]

    monkeypatch_local = pytest.MonkeyPatch()
    monkeypatch_local.setattr(cli, "_execute_route", fake_execute_route)

    cli.etf_historical(symbol="510300.XSHG", limit=2)

    output = json.loads(capsys.readouterr().out)
    assert len(output) == 2

    monkeypatch_local.undo()


def test_historical_limit_not_forwarded_to_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    called_params: dict[str, Any] = {}

    def fake_execute_route(route: str, **params: Any) -> list[dict[str, Any]]:
        called_params.update(params)
        return [{"symbol": "AAPL"}]

    monkeypatch.setattr(cli, "_execute_route", fake_execute_route)
    monkeypatch.setitem(
        cli.COMMAND_EXECUTORS,
        "equity.price.historical",
        cli._historical_executor("equity.price.historical"),
    )

    result = cli.COMMAND_EXECUTORS["equity.price.historical"](
        {"symbol": "AAPL", "__cli_limit__": 5},
    )

    assert "__cli_limit__" not in called_params
    assert len(result) == 1


def test_equity_overview_template_includes_historical_limit() -> None:
    queries = cli._build_template_queries(
        "equity-overview",
        {
            "symbol": "AAPL",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "limit": 30,
            "news_limit": 5,
            "options_limit": 6,
        },
    )

    historical_params = queries[1]["params"]
    assert historical_params["__cli_limit__"] == 30


def test_index_detail_template_includes_historical_limit() -> None:
    queries = cli._build_template_queries(
        "index-detail",
        {
            "symbol": "000001.XSHG",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "limit": 50,
        },
    )

    historical_params = queries[1]["params"]
    assert historical_params["__cli_limit__"] == 50
