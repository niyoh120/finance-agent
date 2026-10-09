from __future__ import annotations

import inspect
import json
import sys
from datetime import date, timedelta
from typing import Any

import pytest
from openbb_agent_cli import cli, executors, output
from openbb_agent_cli import options_chain as oc


class DummyResult:
    def model_dump(self, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return {"results": [{"symbol": "AAPL"}]}


def test_run_route_reports_stripped_null_fields(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_execute_route(route: str, **params: Any) -> list[dict[str, Any]]:
        assert route == "equity.search"
        assert {key: value for key, value in params.items() if value is not None} == {
            "query": "AAPL",
            "is_symbol": False,
        }
        return [{"symbol": "AAPL", "note": None}]

    monkeypatch.setattr(executors, "_execute_route", fake_execute_route)
    monkeypatch.setattr(output, "model_field_descriptions", lambda name: {"symbol": "Symbol", "note": "Note"})

    cli._run_route("equity.search", query="AAPL", is_symbol=False, start_date=None)

    assert json.loads(capsys.readouterr().out) == {
        "results": [{"symbol": "AAPL"}],
        "_schema": {"symbol": "Symbol", "note": "Note"},
        "_meta": {"null_stripped_fields": ["note"]},
    }


def test_run_route_suppresses_provider_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeQuery:
        def __init__(self, cc, provider_choices, standard, extra) -> None:
            pass

        async def execute(self) -> list[DummyResult]:
            print("provider stdout")
            print("provider stderr", file=sys.stderr)
            return [DummyResult()]

    monkeypatch.setattr("openbb_core.app.query.Query", FakeQuery)
    monkeypatch.setattr(output, "model_field_descriptions", lambda name: {"results": "Data records"})

    cli._run_route("equity.search", query="AAPL")

    captured = capsys.readouterr()
    assert captured.out == '{"results":[{"results":[{"symbol":"AAPL"}]}],"_schema":{"results":"Data records"}}\n'
    assert captured.err == ""


def test_derivatives_options_query_outputs_results_meta_without_schema(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """自由 SQL 动态列：无 _schema，空串保留，None 删除，_meta 保留零值。"""

    async def fake_fetch_query(sql: str, max_rows: int | None = None) -> dict[str, Any]:
        assert sql == "SELECT 1"
        assert max_rows == 10
        return {"rows": [{"col": "", "n": None, "z": 0}], "row_count": 5, "truncated": True, "elapsed_ms": 7}

    monkeypatch.setattr("openbb_finance.sources.convexvalue.fetch_query", fake_fetch_query)

    cli.derivatives_options_query(sql="SELECT 1", max_rows=10)

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "results": [{"col": "", "z": 0}],
        "_meta": {
            "returned": 1,
            "row_count": 5,
            "truncated": True,
            "elapsed_ms": 7,
            "null_stripped_fields": ["n"],
        },
    }
    assert "_schema" not in payload


def test_derivatives_options_screener_outputs_schema_and_meta(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def fake_fetch_screen(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["limit"] == 50
        return {
            "columns": ["underlying_ticker", "open_interest"],
            "rows": [["SPY", 1000], ["QQQ", None]],
            "row_count": 2,
            "truncated": False,
        }

    monkeypatch.setattr("openbb_finance.sources.convexvalue.fetch_screen", fake_fetch_screen)
    monkeypatch.setattr(output, "model_field_descriptions", lambda name: {"underlying_ticker": "Underlying"})

    cli.derivatives_options_screener()

    payload = json.loads(capsys.readouterr().out)
    assert payload["results"] == [{"underlying_ticker": "SPY", "open_interest": 1000}, {"underlying_ticker": "QQQ"}]
    assert payload["_schema"] == {"underlying_ticker": "Underlying", "open_interest": "open_interest"}
    assert payload["_meta"] == {
        "returned": 2,
        "row_count": 2,
        "truncated": False,
        "sort_by": "open_interest",
        "sort_dir": "desc",
        "null_stripped_fields": ["open_interest"],
    }


def test_run_route_dynamic_screener_omits_schema(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_execute_route(route: str, **params: Any) -> list[dict[str, Any]]:
        assert route == "equity.screener"
        return [{"symbol": "AAPL", "sector": ""}]

    monkeypatch.setattr(executors, "_execute_route", fake_execute_route)

    cli._run_route("equity.screener", market="america", volume_min=1)

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"results": [{"symbol": "AAPL"}]}
    assert "_schema" not in payload


def test_run_route_outputs_json_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def command(provider: str, **params: Any) -> DummyResult:
        raise RuntimeError("boom")

    monkeypatch.setattr(executors, "_execute_route", lambda route, **params: command(provider="finance", **params))

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


def test_technical_indicators_uses_extra_params_and_limit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, Any] = {}

    def execute_provider_model(
        model_name: str,
        standard_params: dict[str, Any] | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        captured["model_name"] = model_name
        captured["standard_params"] = standard_params
        captured["extra_params"] = extra_params
        return [{"i": 1}, {"i": 2}, {"i": 3}]

    monkeypatch.setattr(cli, "_execute_provider_model", execute_provider_model)
    monkeypatch.setattr(output, "model_field_descriptions", lambda name: {"i": "Indicator value"})

    cli.technical_indicators(
        symbol="600519.XSHG",
        start_date="2026-04-01",
        indicators=["rsi", "macd"],
        rsi_length=7,
        macd_fast=5,
        macd_slow=15,
        limit=2,
    )

    assert captured["model_name"] == "TechnicalIndicators"
    assert captured["standard_params"] == {}
    for key, value in {
        "symbol": "600519.XSHG",
        "start_date": "2026-04-01",
        "interval": "1d",
        "adjusted": False,
        "indicators": ["rsi", "macd"],
        "rsi_length": 7,
        "macd_fast": 5,
        "macd_slow": 15,
    }.items():
        assert captured["extra_params"][key] == value
    assert "limit" not in captured["extra_params"]
    assert captured["extra_params"]["sma_lengths"] == [20, 50]
    assert captured["extra_params"]["ema_lengths"] == [20]
    assert json.loads(capsys.readouterr().out) == {
        "results": [{"i": 2}, {"i": 3}],
        "_schema": {"i": "Indicator value"},
    }


def test_technical_indicators_executor_supports_batch_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def execute_provider_model(
        model_name: str,
        standard_params: dict[str, Any] | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        captured["model_name"] = model_name
        captured["standard_params"] = standard_params
        captured["extra_params"] = extra_params
        return [{"i": 1}, {"i": 2}, {"i": 3}]

    monkeypatch.setattr(executors, "_execute_provider_model", execute_provider_model)

    result = cli.COMMAND_EXECUTORS["technical.indicators"](
        {"symbol": "AAPL", "indicators": "rsi", "limit": 1},
    )

    assert result == [{"i": 3}]
    assert captured["model_name"] == "TechnicalIndicators"
    assert captured["standard_params"] == {}
    assert "limit" not in captured["extra_params"]
    assert captured["extra_params"]["symbol"] == "AAPL"
    assert captured["extra_params"]["indicators"] == ["rsi"]
    assert captured["extra_params"]["interval"] == "1d"


def test_technical_indicators_executor_rejects_missing_symbol() -> None:
    with pytest.raises(ValueError, match="technical.indicators requires symbol"):
        cli.COMMAND_EXECUTORS["technical.indicators"]({})


def test_technical_indicators_empty_lists_use_defaults() -> None:
    params = cli._technical_indicators_params(
        symbol="AAPL",
        indicators=[],
        sma_lengths=[],
        ema_lengths=[],
    )

    assert params["indicators"] == ["rsi", "macd", "sma", "ema", "bbands", "atr", "stoch", "vwap"]
    assert params["sma_lengths"] == [20, 50]
    assert params["ema_lengths"] == [20]


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


def test_equity_screener_no_args_returns_help(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def run_route(route: str, **params: Any) -> None:
        pytest.fail("equity.screener without filters should return help, not call the provider")

    monkeypatch.setattr(cli, "_run_route", run_route)

    cli.equity_screener()

    payload = json.loads(capsys.readouterr().out)
    assert payload["usage"] == "openbb-agent-cli equity.screener [OPTIONS]"
    assert "simple_filters" in payload
    assert "advanced" in payload
    assert "field_discovery" in payload


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"filters": '{"PE_RATIO_TTM":{"max":20}}'}, {"filters": '{"PE_RATIO_TTM":{"max":20}}'}),
        ({"sector": ["Technology"]}, {"sector": ["Technology"]}),
        (
            {"market": "america", "change_percent_min": 5.0, "fields": '["SYMBOL","PRICE"]'},
            {"market": "america", "change_percent_min": 5.0, "fields": '["SYMBOL","PRICE"]'},
        ),
        ({"market": "america", "volume_min": 1}, {"market": "america", "volume_min": 1}),
    ],
)
def test_equity_screener_with_required_filters_not_help(
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    captured: dict[str, Any] = {}

    def run_route(route: str, **params: Any) -> None:
        captured["route"] = route
        captured["params"] = params

    monkeypatch.setattr(cli, "_run_route", run_route)

    cli.equity_screener(**kwargs)

    assert captured["route"] == "equity.screener"
    for key, value in expected.items():
        assert captured["params"][key] == value


@pytest.mark.parametrize(
    "kwargs",
    [
        {"market": "america"},
        {"limit": 10},
        {"fields": '["SYMBOL","PRICE"]'},
        {"market": "america", "limit": 10, "fields": '["SYMBOL","PRICE"]'},
        {"sector": []},
        {"filters": ""},
        {"filters": "   "},
        {"sector": [""]},
        {"sector": ["   "]},
    ],
)
def test_equity_screener_scope_or_output_only_returns_help(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    kwargs: dict[str, Any],
) -> None:
    def run_route(route: str, **params: Any) -> None:
        pytest.fail("scope/output options without required filters should return help")

    monkeypatch.setattr(cli, "_run_route", run_route)

    cli.equity_screener(**kwargs)

    payload = json.loads(capsys.readouterr().out)
    assert payload["usage"] == "openbb-agent-cli equity.screener [OPTIONS]"
    assert "simple_filters" in payload
    assert "advanced" in payload
    assert "field_discovery" in payload


def test_equity_screener_required_filter_tuple_matches_signature() -> None:
    expected = {
        "price_min",
        "price_max",
        "change_percent_min",
        "change_percent_max",
        "volume_min",
        "volume_max",
        "market_cap_min",
        "market_cap_max",
        "rsi_min",
        "rsi_max",
        "sector",
        "filters",
    }

    assert set(cli._SCREENER_REQUIRED_FILTER_PARAMS) == expected


def test_equity_screener_fields_no_args_returns_help(capsys: pytest.CaptureFixture[str]) -> None:
    cli.equity_screener_fields()

    payload = json.loads(capsys.readouterr().out)
    assert payload["usage"] == "openbb-agent-cli equity.screener.fields [OPTIONS]"
    assert "search_hints" in payload
    assert "unclassified" in payload


def test_equity_screener_fields_search(capsys: pytest.CaptureFixture[str]) -> None:
    pytest.importorskip("tvscreener")

    cli.equity_screener_fields(search="RSI")

    payload = json.loads(capsys.readouterr().out)
    assert payload
    assert all({"name", "label"} <= item.keys() for item in payload)
    assert any("RSI" in (item["name"] + item["label"]).upper() for item in payload)


def test_equity_screener_fields_search_dividend(capsys: pytest.CaptureFixture[str]) -> None:
    pytest.importorskip("tvscreener")

    cli.equity_screener_fields(search="dividend")

    payload = json.loads(capsys.readouterr().out)
    assert payload
    assert any("DIVIDEND" in (item["name"] + item["label"]).upper() for item in payload)


def test_equity_screener_fields_all(capsys: pytest.CaptureFixture[str]) -> None:
    pytest.importorskip("tvscreener")
    from tvscreener import StockField

    cli.equity_screener_fields(all_=True)

    payload = json.loads(capsys.readouterr().out)
    names = {item["name"] for item in payload}
    assert len(payload) == len(list(StockField))
    assert {"PRICE", "VOLUME"} <= names


def test_equity_screener_fields_search_and_all_mutually_exclusive(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.equity_screener_fields(search="RSI", all_=True)

    assert exc_info.value.code == 1
    assert json.loads(capsys.readouterr().out) == {
        "error": "--search and --all are mutually exclusive",
        "code": "CLI_ERROR",
    }


def test_equity_screener_fields_empty_search(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.equity_screener_fields(search="   ")

    assert exc_info.value.code == 1
    assert json.loads(capsys.readouterr().out) == {
        "error": "--search keyword must not be empty",
        "code": "CLI_ERROR",
    }


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

    monkeypatch.setitem(cli.COMMAND_EXECUTORS, "equity.price.quote", quote_executor)
    monkeypatch.setitem(cli.COMMAND_EXECUTORS, "equity.search", failing_executor)
    monkeypatch.setattr(output, "model_field_descriptions", lambda name: {"symbol": "Symbol"})

    payload = cli._run_batch_queries(
        [
            {"name": "quote", "command": "equity.price.quote", "params": {"symbol": "AAPL"}},
            {"name": "failed", "command": "equity.search"},
        ],
        max_workers=2,
    )

    assert payload == {
        "results": {
            "quote": {
                "results": [{"symbol": "AAPL", "price": 100}],
                "_schema": {"symbol": "Symbol", "price": "price"},
            }
        },
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

    monkeypatch.setitem(cli.COMMAND_EXECUTORS, "equity.search", first_executor)
    monkeypatch.setitem(cli.COMMAND_EXECUTORS, "equity.price.quote", second_executor)
    monkeypatch.setattr(output, "model_field_descriptions", lambda name: {})

    payload = cli._run_batch_queries(
        [
            {"name": "first", "command": "equity.search"},
            {"name": "second", "command": "equity.price.quote"},
        ],
        max_workers=2,
    )

    assert events == ["first", "second"]
    assert payload["errors"] == {}
    assert payload["results"]["first"] == {"results": [], "_schema": {}}
    assert payload["results"]["second"] == {"results": [], "_schema": {}}


def test_run_batch_queries_preserves_repeated_unnamed_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        cli.COMMAND_EXECUTORS,
        "equity.price.quote",
        lambda params: [{"symbol": params["symbol"]}],
    )
    monkeypatch.setattr(output, "model_field_descriptions", lambda name: {"symbol": "Symbol"})

    payload = cli._run_batch_queries(
        [
            {"command": "equity.price.quote", "params": {"symbol": "AAPL"}},
            {"command": "equity.price.quote", "params": {"symbol": "MSFT"}},
        ],
        max_workers=2,
    )

    assert payload == {
        "results": {
            "0": {"results": [{"symbol": "AAPL"}], "_schema": {"symbol": "Symbol"}},
            "1": {"results": [{"symbol": "MSFT"}], "_schema": {"symbol": "Symbol"}},
        },
        "errors": {},
    }


def test_batch_outputs_json_payload(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setitem(
        cli.COMMAND_EXECUTORS,
        "equity.price.quote",
        lambda params: [{"symbol": params["symbol"]}],
    )
    monkeypatch.setattr(output, "model_field_descriptions", lambda name: {"symbol": "Symbol"})

    cli.batch(queries='[{"name":"quote","command":"equity.price.quote","params":{"symbol":"AAPL"}}]')

    assert json.loads(capsys.readouterr().out) == {
        "results": {"quote": {"results": [{"symbol": "AAPL"}], "_schema": {"symbol": "Symbol"}}},
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


def test_market_overview_template_includes_required_screener_filter() -> None:
    queries = cli._build_template_queries("market-overview", {"region": "us", "limit": 20})

    movers = next(query for query in queries if query["name"] == "movers")
    assert movers == {
        "name": "movers",
        "command": "equity.screener",
        "params": {"market": "america", "volume_min": 1, "limit": 20},
    }


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
    monkeypatch_local.setattr(executors, "_execute_route", fake_execute_route)

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
    monkeypatch_local.setattr(executors, "_execute_route", fake_execute_route)

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

    output_payload = json.loads(capsys.readouterr().out)
    assert len(output_payload["results"]) == 5
    assert called_with["route"] == "equity.price.historical"
    assert called_with.get("limit") is None

    monkeypatch_local.undo()


def test_index_price_historical_passes_limit(capsys: pytest.CaptureFixture[str]) -> None:
    def fake_execute_route(route: str, **params: Any) -> list[dict[str, Any]]:
        return [{"symbol": "000001.XSHG", "i": i} for i in range(8)]

    monkeypatch_local = pytest.MonkeyPatch()
    monkeypatch_local.setattr(cli, "_execute_route", fake_execute_route)

    cli.index_price_historical(symbol="000001.XSHG", limit=3)

    output_payload = json.loads(capsys.readouterr().out)
    assert len(output_payload["results"]) == 3
    assert output_payload["results"][0]["i"] == 5

    monkeypatch_local.undo()


def test_etf_historical_passes_limit(capsys: pytest.CaptureFixture[str]) -> None:
    def fake_execute_route(route: str, **params: Any) -> list[dict[str, Any]]:
        return [{"symbol": "510300.XSHG", "i": i} for i in range(6)]

    monkeypatch_local = pytest.MonkeyPatch()
    monkeypatch_local.setattr(cli, "_execute_route", fake_execute_route)

    cli.etf_historical(symbol="510300.XSHG", limit=2)

    output_payload = json.loads(capsys.readouterr().out)
    assert len(output_payload["results"]) == 2
    assert set(output_payload["_schema"]) >= {"symbol", "date", "open", "close"}

    monkeypatch_local.undo()


def test_index_price_historical_forwards_interval(capsys: pytest.CaptureFixture[str]) -> None:
    called_with: dict[str, Any] = {}

    def fake_execute_route(route: str, **params: Any) -> list[dict[str, Any]]:
        called_with.update({"route": route, **params})
        return [{"symbol": "000300.XSHG", "date": "2026-09-18T09:35:00", "close": 1.5}]

    monkeypatch_local = pytest.MonkeyPatch()
    monkeypatch_local.setattr(cli, "_execute_route", fake_execute_route)

    cli.index_price_historical(symbol="000300.XSHG", interval="5m")

    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["date"] == "2026-09-18T09:35:00"
    assert called_with["route"] == "index.price.historical"
    assert called_with["interval"] == "5m"

    monkeypatch_local.undo()


def test_etf_historical_forwards_interval(capsys: pytest.CaptureFixture[str]) -> None:
    called_with: dict[str, Any] = {}

    def fake_execute_route(route: str, **params: Any) -> list[dict[str, Any]]:
        called_with.update({"route": route, **params})
        return [{"symbol": "SPY", "date": "2026-09-18T09:35:00", "close": 1.5}]

    monkeypatch_local = pytest.MonkeyPatch()
    monkeypatch_local.setattr(cli, "_execute_route", fake_execute_route)

    cli.etf_historical(symbol="SPY", interval="10m")

    assert called_with["route"] == "etf.historical"
    assert called_with["interval"] == "10m"

    monkeypatch_local.undo()


def test_index_price_historical_positional_limit_keeps_binding(capsys: pytest.CaptureFixture[str]) -> None:
    """interval appends after limit: existing positional calls keep semantics."""
    called_with: dict[str, Any] = {}

    def fake_execute_route(route: str, **params: Any) -> list[dict[str, Any]]:
        called_with.update(params)
        return [{"symbol": "000001.XSHG", "i": i} for i in range(8)]

    monkeypatch_local = pytest.MonkeyPatch()
    monkeypatch_local.setattr(cli, "_execute_route", fake_execute_route)

    cli.index_price_historical("000001.XSHG", "2026-01-01", "2026-01-31", 3)

    output_payload = json.loads(capsys.readouterr().out)
    assert len(output_payload["results"]) == 3
    assert "limit" not in called_with
    assert called_with["interval"] == "1d"

    monkeypatch_local.undo()


def test_historical_executor_forwards_default_and_explicit_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []

    def fake_execute_route(route: str, **params: Any) -> list[dict[str, Any]]:
        seen.append(params)
        return [{"symbol": "SPX", "close": 1.0}]

    monkeypatch.setattr(executors, "_execute_route", fake_execute_route)

    cli.COMMAND_EXECUTORS["index.price.historical"]({"symbol": "SPX"})
    cli.COMMAND_EXECUTORS["etf.historical"]({"symbol": "SPY", "interval": "5m"})

    assert seen[0]["interval"] == "1d"
    assert seen[1]["interval"] == "5m"


def test_index_detail_template_passes_interval_to_historical_only() -> None:
    queries = cli._build_template_queries(
        "index-detail",
        {"symbol": "000001.XSHG", "region": "cn", "limit": 50, "interval": "5m"},
    )

    snapshot, historical = queries[0]["params"], queries[1]["params"]
    assert "interval" in historical
    assert historical["interval"] == "5m"
    assert "interval" not in snapshot


def test_index_detail_template_omits_interval_when_unset() -> None:
    queries = cli._build_template_queries(
        "index-detail",
        {"symbol": "000001.XSHG", "region": "cn", "limit": 50},
    )

    assert "interval" not in queries[1]["params"]


def test_equity_overview_template_passes_interval_to_historical_only() -> None:
    queries = cli._build_template_queries(
        "equity-overview",
        {"symbol": "AAPL", "limit": 30, "interval": "15m"},
    )

    by_name = {query["name"]: query for query in queries}
    assert by_name["historical"]["params"]["interval"] == "15m"
    assert by_name["quote"]["params"] == {"symbol": "AAPL"}
    assert "interval" not in by_name["news"]["params"]


def test_historical_limit_not_forwarded_to_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    called_params: dict[str, Any] = {}

    def fake_execute_route(route: str, **params: Any) -> list[dict[str, Any]]:
        called_params.update(params)
        return [{"symbol": "AAPL"}]

    monkeypatch.setattr(executors, "_execute_route", fake_execute_route)
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


def test_is_market_open_returns_false_on_weekend() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    # Saturday 2026-07-04 10:00 Beijing, all three markets closed.
    saturday = datetime(2026, 7, 4, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    monkeypatch_dt = type(
        "DT",
        (),
        {"now": staticmethod(lambda tz=None: saturday.astimezone(tz) if tz else saturday.replace(tzinfo=None))},
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(executors, "datetime", monkeypatch_dt)
    try:
        assert cli._is_market_open("cn") is False
        assert cli._is_market_open("hk") is False
        assert cli._is_market_open("us") is False
    finally:
        monkeypatch.undo()


def test_is_market_open_cn_during_session() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    # Wednesday 2026-07-01 10:00 Beijing -> CN session (9:30-11:30).
    morning = datetime(2026, 7, 1, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    monkeypatch_dt = type(
        "DT", (), {"now": staticmethod(lambda tz=None: morning.astimezone(tz) if tz else morning.replace(tzinfo=None))}
    )
    mp = pytest.MonkeyPatch()
    mp.setattr(executors, "datetime", monkeypatch_dt)
    try:
        assert cli._is_market_open("cn") is True
    finally:
        mp.undo()


def test_historical_executor_skips_intraday_tag_when_symbol_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{"date": "2026-07-03", "close": 100.0}]

    monkeypatch.setattr(executors, "_execute_route", lambda route, **params: rows)

    def fail_tag(symbol: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        raise AssertionError("tagging should be skipped when symbol is missing")

    monkeypatch.setattr(executors, "_tag_intraday_last_bar", fail_tag)

    executor = cli._historical_executor("equity.price.historical")
    assert executor({}) is rows


def test_tag_intraday_last_bar_passthrough_when_market_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(executors, "_is_market_open", lambda market: False)
    rows = [{"date": "2026-07-03", "close": 100.0}, {"date": "2026-07-04", "close": 101.0}]
    result = cli._tag_intraday_last_bar("AAPL", rows)
    assert result is rows  # no copy when market closed
    assert "_meta" not in result[-1]


def test_tag_intraday_last_bar_tags_today_bar_when_market_open(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    monkeypatch.setattr(executors, "_is_market_open", lambda market: True)
    monkeypatch.setattr(executors, "infer_market_from_symbol", lambda symbol: "cn")
    # Fix "now" to 2026-07-04 10:00 Beijing so today == last bar's date.
    fixed = datetime(2026, 7, 4, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    monkeypatch.setattr(
        executors,
        "datetime",
        type(
            "DT", (), {"now": staticmethod(lambda tz=None: fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None))}
        ),
    )

    rows = [{"date": "2026-07-03", "close": 100.0}, {"date": "2026-07-04", "close": 101.0}]
    result = cli._tag_intraday_last_bar("510300.XSHG", rows)
    assert len(result) == 2
    assert result[0] == rows[0]  # earlier bars untouched
    assert result[-1]["_meta"]["warning"]
    assert result[-1]["_meta"]["market"] == "cn"
    assert "_meta" not in rows[-1]  # original list not mutated


def test_tag_intraday_last_bar_no_tag_when_last_bar_not_today(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    monkeypatch.setattr(executors, "_is_market_open", lambda market: True)
    monkeypatch.setattr(executors, "infer_market_from_symbol", lambda symbol: "cn")
    # Freeze "now" so the test is deterministic regardless of the real wall-clock date.
    fixed = datetime(2026, 7, 3, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    monkeypatch.setattr(
        executors,
        "datetime",
        type(
            "DT", (), {"now": staticmethod(lambda tz=None: fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None))}
        ),
    )
    rows = [{"date": "2026-07-01", "close": 100.0}, {"date": "2026-07-02", "close": 101.0}]
    result = cli._tag_intraday_last_bar("510300.XSHG", rows)
    assert result is rows  # passthrough, no copy
    assert "_meta" not in result[-1]


def test_is_market_open_us_session_on_beijing_saturday(monkeypatch: pytest.MonkeyPatch) -> None:
    # Friday 10:00 ET (DST) == Saturday 00:00 Beijing. The US market is open, so the
    # Beijing-time weekend guard must NOT suppress it. The cross-midnight boundary is
    # the critical case for the US branch. Use a non-holiday Friday (2026-07-10) so the
    # test isolates the timezone boundary rather than the documented holiday gap.
    from datetime import datetime
    from zoneinfo import ZoneInfo

    fixed = datetime(2026, 7, 11, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    monkeypatch.setattr(
        executors,
        "datetime",
        type(
            "DT", (), {"now": staticmethod(lambda tz=None: fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None))}
        ),
    )
    assert cli._is_market_open("us") is True


def test_tag_intraday_last_bar_tags_us_bar_during_beijing_saturday_session(monkeypatch: pytest.MonkeyPatch) -> None:
    # US daily bar is dated by the US trading day (Friday 2026-07-10), even though it is
    # already Saturday in Beijing. The tag must compare against the US-local date, not
    # the Beijing date, otherwise the partial bar is never flagged.
    from datetime import datetime
    from zoneinfo import ZoneInfo

    fixed = datetime(2026, 7, 11, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    monkeypatch.setattr(
        executors,
        "datetime",
        type(
            "DT", (), {"now": staticmethod(lambda tz=None: fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None))}
        ),
    )
    monkeypatch.setattr(executors, "infer_market_from_symbol", lambda symbol: "us")

    rows = [{"date": "2026-07-10", "close": 100.0}]  # US trading-day date
    result = cli._tag_intraday_last_bar("AAPL", rows)
    assert result[-1]["_meta"]["market"] == "us"


def test_futures_routes_registered() -> None:
    assert cli.ROUTE_MODELS["futures.price.historical"] == "FuturesHistorical"
    assert cli.ROUTE_MODELS["futures.price.quote"] == "FuturesQuote"
    assert cli.ROUTE_MODELS["futures.search"] == "FuturesSearch"
    assert "futures.price.historical" in cli.COMMAND_EXECUTORS
    assert "futures.price.quote" in cli.COMMAND_EXECUTORS
    assert "futures.search" in cli.COMMAND_EXECUTORS


def test_futures_price_historical_command_routes_params(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    captured: dict[str, Any] = {}

    def fake_execute_route(route: str, **params: Any) -> list[dict[str, Any]]:
        captured["route"] = route
        captured["params"] = params
        return [{"date": "2026-08-07", "close": 3010.0}]

    monkeypatch.setattr(cli, "_execute_route", fake_execute_route)

    cli.futures_price_historical(symbol="rb.SHFE", expiration="2026-10", limit=1)

    assert captured["route"] == "futures.price.historical"
    assert captured["params"] == {
        "symbol": "rb.SHFE",
        "expiration": "2026-10",
        "start_date": None,
        "end_date": None,
        "interval": "1d",
        "adjusted": False,
    }
    assert json.loads(capsys.readouterr().out)["results"] == [{"date": "2026-08-07", "close": 3010.0}]


def test_futures_price_quote_command_routes_params(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_execute_route(route: str, **params: Any) -> list[dict[str, Any]]:
        captured["route"] = route
        captured["params"] = params
        return []

    monkeypatch.setattr(executors, "_execute_route", fake_execute_route)

    cli.futures_price_quote(symbol="GC.COMEX")

    assert captured["route"] == "futures.price.quote"
    assert captured["params"] == {"symbol": "GC.COMEX", "expiration": None}


def test_futures_search_command_routes_params(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_execute_route(route: str, **params: Any) -> list[dict[str, Any]]:
        captured["route"] = route
        captured["params"] = params
        return []

    monkeypatch.setattr(executors, "_execute_route", fake_execute_route)

    cli.futures_search(query="工业硅")

    assert captured["route"] == "futures.search"
    assert captured["params"] == {"query": "工业硅", "is_symbol": False}


def test_futures_historical_executor_applies_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    called_params: dict[str, Any] = {}

    def fake_execute_route(route: str, **params: Any) -> list[dict[str, Any]]:
        called_params.update(params)
        return [{"date": "2026-08-07", "close": 3010.0}]

    monkeypatch.setattr(executors, "_execute_route", fake_execute_route)

    result = cli.COMMAND_EXECUTORS["futures.price.historical"](
        {"symbol": "rb.SHFE", "limit": 1},
    )

    assert called_params["interval"] == "1d"
    assert called_params["adjusted"] is False
    assert len(result) == 1


def test_execute_provider_model_strips_query_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    """The generated standard/extra dataclasses must not leak fastapi Query(...)
    markers into the fetcher's pydantic QueryParams for unset optional fields."""
    import dataclasses

    captured: dict[str, Any] = {}

    class FakeQuery:
        def __init__(self, cc, provider_choices, standard, extra) -> None:
            self.standard = standard
            self.extra = extra

        async def execute(self) -> list[dict[str, Any]]:
            captured["standard"] = dataclasses.asdict(self.standard)
            captured["extra"] = dataclasses.asdict(self.extra)
            return []

    monkeypatch.setattr("openbb_core.app.query.Query", FakeQuery)

    cli._execute_provider_model("FuturesQuote", None, {"symbol": "rb.SHFE"})

    assert captured["standard"] == {}
    assert captured["extra"] == {"symbol": "rb.SHFE", "expiration": None}
    assert not any(type(value).__name__ == "Query" for value in captured["extra"].values())


# ---- derivatives.options.chain: query validation (pure functions) --------------

_CHAIN_AS_OF = date(2026, 10, 9)


def test_options_chain_command_signature_drops_legacy_flags() -> None:
    """The public command surface must not carry the retired window/source flags."""
    params = set(inspect.signature(cli.derivatives_options_chain).parameters)
    assert {"dte", "strike_count", "min_dte", "source", "range_", "strategy"}.isdisjoint(params)
    legacy_free = {"symbol", "expiration", "dte_min", "dte_max", "atm", "option_type", "sort_by", "sort_dir", "limit"}
    assert legacy_free <= params


@pytest.mark.parametrize(
    ("kwargs", "expected_mode", "expected_from", "expected_to"),
    [
        ({}, "dte", _CHAIN_AS_OF, _CHAIN_AS_OF + timedelta(days=45)),  # defaults 0..45
        ({"dte_max": 30}, "dte", _CHAIN_AS_OF, _CHAIN_AS_OF + timedelta(days=30)),  # only upper bound
        ({"dte_min": 40}, "dte", _CHAIN_AS_OF + timedelta(days=40), _CHAIN_AS_OF + timedelta(days=45)),
        ({"dte_min": 0, "dte_max": 0}, "dte", _CHAIN_AS_OF, _CHAIN_AS_OF),
        (
            {"dte_min": 700, "dte_max": 1000},
            "dte",
            _CHAIN_AS_OF + timedelta(days=700),
            _CHAIN_AS_OF + timedelta(days=1000),
        ),
        (
            {"dte_min": 700, "dte_max": 1065},
            "dte",
            _CHAIN_AS_OF + timedelta(days=700),
            _CHAIN_AS_OF + timedelta(days=1065),
        ),  # span exactly 365
        ({"expiration": "2026-10-09"}, "expiration", _CHAIN_AS_OF, _CHAIN_AS_OF),  # today is accepted
        ({"expiration": "2028-01-21"}, "expiration", date(2028, 1, 21), date(2028, 1, 21)),
    ],
)
def test_resolve_date_window_valid_windows(
    kwargs: dict[str, Any], expected_mode: str, expected_from: date, expected_to: date
) -> None:
    window = oc.resolve_date_window(as_of_date=_CHAIN_AS_OF, **kwargs)

    assert window.mode == expected_mode
    assert window.from_date == expected_from
    assert window.to_date == expected_to
    assert window.span == (expected_to - expected_from).days


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"expiration": "2026-10-10", "dte_min": 3}, "mutually exclusive"),
        ({"expiration": "2026-10-10", "dte_max": 3}, "mutually exclusive"),
        ({"dte_min": 700}, "dte_min must be <= dte_max"),  # 700 above default dte_max=45
        ({"dte_min": 30, "dte_max": 10}, "dte_min must be <= dte_max"),
        ({"dte_min": 0, "dte_max": 366}, "span must be <= 365"),
        ({"dte_min": 700, "dte_max": 1066}, "span must be <= 365"),
        ({"dte_min": -1}, "non-negative"),
        ({"dte_max": -5}, "non-negative"),
        ({"dte_min": 1.5}, "must be an integer"),
        ({"dte_max": True}, "must be an integer"),
        ({"expiration": "2026-10-8"}, "YYYY-MM-DD"),
        ({"expiration": "20261009"}, "YYYY-MM-DD"),
        ({"expiration": "2026-13-01"}, "YYYY-MM-DD"),
        ({"expiration": "2026-10-08"}, "today or later"),  # one day before as_of
        ({"expiration": "2020-01-01"}, "today or later"),
        ({"dte_min": 100_000_000, "dte_max": 100_000_365}, "overflows"),
    ],
)
def test_resolve_date_window_invalid_windows(kwargs: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        oc.resolve_date_window(as_of_date=_CHAIN_AS_OF, **kwargs)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"symbol": ""}, "symbol is required"),
        ({"symbol": "   "}, "symbol is required"),
        ({"symbol": "SPY", "atm": 0}, "atm must be between"),
        ({"symbol": "SPY", "atm": 101}, "atm must be between"),
        ({"symbol": "SPY", "atm": True}, "must be an integer"),
        ({"symbol": "SPY", "atm": 2.5}, "must be an integer"),
        ({"symbol": "SPY", "limit": -1}, "non-negative"),
        ({"symbol": "SPY", "limit": 2.5}, "must be an integer"),
        ({"symbol": "SPY", "limit": False}, "must be an integer"),
        ({"symbol": "SPY", "option_type": "Call"}, "option_type must be one of"),
        ({"symbol": "SPY", "sort_by": "foo"}, "sort_by must be one of"),
        ({"symbol": "SPY", "sort_dir": "ASC"}, "sort_dir must be one of"),
    ],
)
def test_build_options_chain_request_rejects_invalid_scalars(kwargs: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        oc.build_options_chain_request(as_of_date=_CHAIN_AS_OF, **kwargs)


@pytest.mark.parametrize(
    ("limit_kwarg", "expected"),
    [
        (None, None),
        (0, None),  # explicit 0 = all filtered contracts
        (5, 5),
    ],
)
def test_build_options_chain_request_limit_semantics(limit_kwarg: int | None, expected: int | None) -> None:
    request = oc.build_options_chain_request(symbol="SPY", limit=limit_kwarg, as_of_date=_CHAIN_AS_OF)
    assert request.limit is expected
    # ATM boundaries: 1 and 100 are valid, defaults apply otherwise.
    assert oc.build_options_chain_request(symbol="SPY", atm=1, as_of_date=_CHAIN_AS_OF).atm == 1
    assert oc.build_options_chain_request(symbol="SPY", atm=100, as_of_date=_CHAIN_AS_OF).atm == 100
    assert oc.build_options_chain_request(symbol="SPY", as_of_date=_CHAIN_AS_OF).atm == 20
    assert oc.build_options_chain_request(symbol="SPY", as_of_date=_CHAIN_AS_OF).limit is None
    assert oc.build_options_chain_request(symbol="SPY", as_of_date=_CHAIN_AS_OF).sort_by == "open_interest"
    assert oc.build_options_chain_request(symbol="SPY", as_of_date=_CHAIN_AS_OF).sort_dir == "desc"


def test_options_chain_batch_executor_rejects_legacy_unknown_and_source_fields() -> None:
    from openbb_agent_cli.executors import _options_chain_batch_executor

    with pytest.raises(ValueError, match="source is no longer supported"):
        _options_chain_batch_executor({"symbol": "SPY", "source": None})  # even explicit null
    with pytest.raises(ValueError, match="source is no longer supported"):
        _options_chain_batch_executor({"symbol": "SPY", "source": "cv"})
    with pytest.raises(ValueError, match=r"\['dte'\].*use dte_min/dte_max"):
        _options_chain_batch_executor({"symbol": "SPY", "dte": 10})
    with pytest.raises(ValueError, match=r"\['strike_count'\].*use atm"):
        _options_chain_batch_executor({"symbol": "SPY", "strike_count": 10})
    with pytest.raises(ValueError, match=r"\['min_dte'\].*use dte_min"):
        _options_chain_batch_executor({"symbol": "SPY", "min_dte": 10})
    with pytest.raises(ValueError, match=r"\['range', 'strategy'\]"):
        _options_chain_batch_executor({"symbol": "SPY", "range": "ITM", "strategy": "VERTICAL"})
    with pytest.raises(ValueError, match="unknown or removed"):
        _options_chain_batch_executor({"symbol": "SPY", "foo": 1})


def test_options_chain_batch_executor_rejects_non_integer_scalars_before_network() -> None:
    from openbb_agent_cli.executors import _options_chain_batch_executor

    with pytest.raises(ValueError, match="atm must be an integer"):
        _options_chain_batch_executor({"symbol": "SPY", "atm": True})
    with pytest.raises(ValueError, match="dte_min must be an integer"):
        _options_chain_batch_executor({"symbol": "SPY", "dte_min": 1.5})
    with pytest.raises(ValueError, match="limit must be an integer"):
        _options_chain_batch_executor({"symbol": "SPY", "limit": 10.5})
    with pytest.raises(ValueError, match="expiration must use the strict YYYY-MM-DD format"):
        _options_chain_batch_executor({"symbol": "SPY", "expiration": "20261010"})


def test_options_chain_batch_executor_limit_defaults_and_explicit_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_execute(params: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        captured.update(params)
        return [], {"returned": 0}

    monkeypatch.setattr(executors, "_options_chain_execute", fake_execute)

    from openbb_agent_cli.executors import _options_chain_batch_executor

    _options_chain_batch_executor({"symbol": "SPY"})  # omitted -> default 100
    assert captured["limit"] == 100
    captured.clear()
    _options_chain_batch_executor({"symbol": "SPY", "limit": None})  # null == omitted
    assert captured["limit"] == 100
    captured.clear()
    _options_chain_batch_executor({"symbol": "SPY", "limit": 0})  # explicit 0 = all
    assert captured["limit"] == 0


# ---- derivatives.options.chain: CLI command and batch integration ---------------


def test_options_chain_command_routes_new_params_and_meta_envelope(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, Any] = {}

    def fake_execute(params: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        captured.update(params)
        return (
            [{"symbol": "SPY", "strike": 500.0, "delta": None}],
            {
                "returned": 1,
                "filtered": 40,
                "total": 120,
                "truncated": False,
                "sort_by": "open_interest",
                "sort_dir": "desc",
                "sources_used": ["schwab", "convexvalue"],
                "cv_enrichment": "success",
                "window": {"mode": "dte", "as_of_date": "2026-10-09", "timezone": "UTC"},
                "atm": 10,
                "atm_reference_price": 500.0,
            },
        )

    monkeypatch.setattr(cli, "_options_chain_execute", fake_execute)
    monkeypatch.setattr(output, "model_field_descriptions", lambda name: {"symbol": "Symbol", "strike": "Strike"})

    cli.derivatives_options_chain(
        "SPY", dte_min=5, dte_max=30, atm=10, option_type="put", sort_by="delta", sort_dir="asc", limit=25
    )

    assert captured == {
        "symbol": "SPY",
        "expiration": None,
        "dte_min": 5,
        "dte_max": 30,
        "atm": 10,
        "option_type": "put",
        "sort_by": "delta",
        "sort_dir": "asc",
        "limit": 25,
    }
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"] == [{"symbol": "SPY", "strike": 500.0}]  # null delta stripped
    assert payload["_meta"]["total"] == 120
    assert payload["_meta"]["filtered"] == 40
    assert payload["_meta"]["returned"] == 1
    assert payload["_meta"]["sources_used"] == ["schwab", "convexvalue"]
    assert payload["_meta"]["cv_enrichment"] == "success"
    assert payload["_meta"]["window"]["mode"] == "dte"
    assert payload["_meta"]["atm"] == 10
    assert payload["_meta"]["atm_reference_price"] == 500.0


def test_options_chain_command_param_error_outputs_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_execute(params: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        raise ValueError("--expiration is mutually exclusive with --dte-min/--dte-max; choose one query mode")

    monkeypatch.setattr(cli, "_options_chain_execute", fake_execute)

    with pytest.raises(SystemExit) as exc_info:
        cli.derivatives_options_chain("SPY", expiration="2026-10-10", dte_min=3)

    assert exc_info.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["code"] == "VALUEERROR"
    assert "mutually exclusive" in payload["error"]


def test_options_chain_command_schwab_missing_outputs_source_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from openbb_finance.sources.base import SourceError

    def fake_execute(params: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        raise SourceError("schwab source is required for derivatives.options.chain but is disabled")

    monkeypatch.setattr(cli, "_options_chain_execute", fake_execute)

    with pytest.raises(SystemExit) as exc_info:
        cli.derivatives_options_chain("SPY", dte_min=0, dte_max=45)

    assert exc_info.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["code"] == "SOURCEERROR"
    assert "schwab source is required" in payload["error"]


def test_batch_chain_subquery_legacy_param_is_isolated_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        cli.COMMAND_EXECUTORS,
        "equity.price.quote",
        lambda params: [{"symbol": params["symbol"]}],
    )
    monkeypatch.setattr(output, "model_field_descriptions", lambda name: {"symbol": "Symbol"})

    payload = cli._run_batch_queries(
        [
            {"name": "chain", "command": "derivatives.options.chain", "params": {"symbol": "SPY", "source": None}},
            {"name": "quote", "command": "equity.price.quote", "params": {"symbol": "AAPL"}},
        ],
        max_workers=2,
    )

    assert "chain" in payload["errors"]
    assert "no longer supported" in payload["errors"]["chain"]["error"]
    assert payload["results"]["quote"] == {"results": [{"symbol": "AAPL"}], "_schema": {"symbol": "Symbol"}}


def test_batch_chain_subquery_success_envelope_drops_chain_meta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_chain_executor(params: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"symbol": "SPY", "strike": 500.0}]

    monkeypatch.setitem(cli.COMMAND_EXECUTORS, "derivatives.options.chain", fake_chain_executor)
    monkeypatch.setattr(output, "model_field_descriptions", lambda name: {"symbol": "Symbol"})

    payload = cli._run_batch_queries(
        [{"name": "chain", "command": "derivatives.options.chain", "params": {"symbol": "SPY"}}],
        max_workers=2,
    )

    # The batch envelope keeps {results, _schema}; chain meta stays CLI-only.
    assert payload["results"]["chain"] == {
        "results": [{"symbol": "SPY", "strike": 500.0}],
        "_schema": {"symbol": "Symbol", "strike": "strike"},  # strike falls back to its own name
    }
    assert payload["errors"] == {}
