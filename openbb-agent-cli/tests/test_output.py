"""Behavior tests for the centralized output shaping (output.py).

Covers the three contract groups from the plan:

1. Cleaning rules: None/exact-"" dropping, 0/False/empty-container
   preservation, nested recursion, array positions, non-mutation and the
   free-SQL empty-string exception.
2. Schema rules: description stripping with field-name fallback, complete
   static field set, final-record extra keys, finance branch selection,
   cache isolation and full command-mapping resolvability.
3. Envelope assembly: static/dynamic commands, meta cleaning and the
   record-level `_meta` handling.
"""

from __future__ import annotations

from typing import Any

import pytest
from openbb_agent_cli import executors, output
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 1. Cleaning rules
# ---------------------------------------------------------------------------


def test_clean_record_drops_none_and_exact_empty_string() -> None:
    record = {"a": None, "b": "", "c": 0, "d": False, "e": [], "f": {}, "g": "  ", "h": "x"}

    assert output.clean_output_record(record) == {"c": 0, "d": False, "e": [], "f": {}, "g": "  ", "h": "x"}


def test_clean_record_recurses_into_nested_dicts_and_lists() -> None:
    record = {
        "nested": {"x": None, "y": 1},
        "rows": [{"a": None, "b": 2}, {"c": "", "d": 0}],
        "scalars": [None, 1, ""],
    }

    cleaned = output.clean_output_record(record)

    assert cleaned == {
        "nested": {"y": 1},
        "rows": [{"b": 2}, {"d": 0}],
        # 标量 null 是位置值，保持原位
        "scalars": [None, 1, ""],
    }


def test_clean_record_keeps_meta_verbatim_and_all_empty_record() -> None:
    record: dict[str, Any] = {"_meta": {"warning": "w", "x": None}, "a": None}

    cleaned = output.clean_output_record(record)

    assert cleaned == {"_meta": {"warning": "w", "x": None}}


def test_clean_record_all_empty_record_cleans_to_empty_dict_in_list() -> None:
    records = [{"a": None, "b": ""}, {"a": 1}]

    cleaned = [output.clean_output_record(record) for record in records]

    assert cleaned == [{}, {"a": 1}]


def test_clean_record_keep_empty_strings_flag() -> None:
    record = {"a": "", "b": None}

    assert output.clean_output_record(record, keep_empty_strings=True) == {"a": ""}
    assert output.clean_output_record(record) == {}


def test_clean_output_record_does_not_mutate_input() -> None:
    record: dict[str, Any] = {"a": None, "b": {"c": None, "d": ""}, "e": [{"f": None}], "g": [None]}
    snapshot: dict[str, Any] = {
        "a": None,
        "b": {"c": None, "d": ""},
        "e": [{"f": None}],
        "g": [None],
    }

    output.clean_output_record(record)

    assert record == snapshot


# ---------------------------------------------------------------------------
# 2. Schema rules
# ---------------------------------------------------------------------------


class _DemoModel(BaseModel):
    symbol: str = Field(description="  The symbol.  ")
    filing_date: str | None = Field(default=None, description=None)
    blank: str | None = Field(default=None, description="   ")


def test_model_field_descriptions_strips_and_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(output, "finance_data_model", lambda name: _DemoModel)

    descriptions = output.model_field_descriptions("_DemoModel")

    assert descriptions == {"symbol": "The symbol.", "filing_date": "filing_date", "blank": "blank"}


def test_finance_branch_selection_for_multi_provider_model() -> None:
    # GdpNominal 注解是 oecd/finance/econdb 的 Union；必须选中 finance 分支。
    assert output.finance_data_model("GdpNominal").__name__ == "FinanceGdpNominalData"
    # 单 provider 模型直接解析；标准模型路由（finance 复用标准模型）同样成立。
    assert output.finance_data_model("EquityQuote").__name__ == "FinanceEquityQuoteData"
    assert output.finance_data_model("EconomicCalendar").__name__ == "EconomicCalendarData"


def test_build_schema_includes_full_static_field_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(output, "model_field_descriptions", lambda name: {"symbol": "Symbol", "bid": "Bid"})

    schema = output.build_schema("EquityQuote", [])

    # 空结果仍提供完整静态字段集
    assert schema == {"symbol": "Symbol", "bid": "Bid"}


def test_build_schema_appends_extra_keys_from_final_records(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(output, "model_field_descriptions", lambda name: {"symbol": "Symbol"})

    schema = output.build_schema("EquityQuote", [{"symbol": "AAPL", "extra_field": None}])

    # 全为 null 的额外字段也进 schema（来自最终结果集），字段名兜底
    assert schema == {"symbol": "Symbol", "extra_field": "extra_field"}


def test_build_schema_describes_record_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(output, "model_field_descriptions", lambda name: {"symbol": "Symbol"})

    schema = output.build_schema("EquityQuote", [{"symbol": "AAPL", "_meta": {"warning": "w"}}])

    assert schema["_meta"] == output.RECORD_META_DESCRIPTION


def test_build_schema_does_not_pollute_cached_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    cached: dict[str, str] = {"symbol": "Symbol"}
    monkeypatch.setattr(output, "model_field_descriptions", lambda name: dict(cached))

    output.build_schema("EquityQuote", [{"extra_field": 1}, {"another": 2}])

    assert output.model_field_descriptions("EquityQuote") == {"symbol": "Symbol"}
    assert cached == {"symbol": "Symbol"}


@pytest.mark.parametrize(("command", "model"), sorted(executors.COMMAND_MODELS.items()))
def test_command_model_resolves_to_finance_data_model(command: str, model: str) -> None:
    data_cls = output.finance_data_model(model)

    assert hasattr(data_cls, "model_fields")
    descriptions = output.model_field_descriptions(model)
    assert descriptions
    assert all(isinstance(value, str) and value for value in descriptions.values())


def test_command_model_mapping_covers_all_static_commands() -> None:
    static_commands = set(executors.COMMAND_EXECUTORS) - executors.DYNAMIC_FIELD_COMMANDS

    unmapped = static_commands - set(executors.COMMAND_MODELS)

    assert unmapped == set()


def test_hyphen_macro_command_maps_to_available_indicators() -> None:
    assert executors.schema_model_for("economy.available-indicators") == "AvailableIndicators"


def test_dynamic_commands_and_empty_string_exception() -> None:
    assert executors.schema_model_for("equity.screener") is None
    assert executors.schema_model_for("derivatives.options.query") is None
    assert executors.keeps_empty_strings("derivatives.options.query") is True
    assert executors.keeps_empty_strings("equity.screener") is False


def test_unmapped_command_fails_loudly() -> None:
    with pytest.raises(ValueError, match="no schema model mapped"):
        executors.schema_model_for("not.a.command")


# ---------------------------------------------------------------------------
# 3. Envelope assembly
# ---------------------------------------------------------------------------


def test_build_success_envelope_static_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(output, "model_field_descriptions", lambda name: {"symbol": "Symbol"})

    envelope = output.build_success_envelope([{"symbol": "AAPL", "bid": None}], model_name="EquityQuote")

    assert envelope == {
        "results": [{"symbol": "AAPL"}],
        "_schema": {"symbol": "Symbol", "bid": "bid"},
    }


def test_build_success_envelope_dynamic_command_omits_schema() -> None:
    envelope = output.build_success_envelope([{"a": "", "b": None}], model_name=None, keep_empty_strings=True)

    assert envelope == {"results": [{"a": ""}]}


def test_build_success_envelope_cleans_meta_protecting_zero_and_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(output, "model_field_descriptions", lambda name: {"symbol": "Symbol"})

    envelope = output.build_success_envelope(
        [{"symbol": "AAPL"}],
        model_name="EquityQuote",
        meta={"returned": 1, "truncated": False, "elapsed_ms": None, "note": ""},
    )

    assert envelope == {
        "results": [{"symbol": "AAPL"}],
        "_schema": {"symbol": "Symbol"},
        "_meta": {"returned": 1, "truncated": False},
    }


def test_build_success_envelope_static_schema_for_empty_results() -> None:
    envelope = output.build_success_envelope([], model_name="EconomicCalendar")

    assert envelope["results"] == []
    assert set(envelope["_schema"]) >= {"date", "country", "category", "event", "importance"}


def test_build_success_envelope_does_not_mutate_input_records(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(output, "model_field_descriptions", lambda name: {"symbol": "Symbol"})
    records: list[dict[str, Any]] = [{"symbol": "AAPL", "bid": None, "nested": {"x": None}}]
    snapshot: list[dict[str, Any]] = [{"symbol": "AAPL", "bid": None, "nested": {"x": None}}]

    output.build_success_envelope(records, model_name="EquityQuote")

    assert records == snapshot


def test_real_model_descriptions_are_usable() -> None:
    descriptions = output.model_field_descriptions("EquityQuote")

    assert descriptions["symbol"]
    assert all(isinstance(value, str) and value == value.strip() for value in descriptions.values())
