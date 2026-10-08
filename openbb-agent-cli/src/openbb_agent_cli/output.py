"""Centralized success-output shaping for the agent CLI data commands.

Turns raw executor records into the agent-facing envelope
``{"results": [...], "_schema": {...}, "_meta": {...}}``:

- ``results`` drops keys whose value is ``None`` (missing data) and exact
  ``""`` (meaningless empty strings), recursively through nested dicts and
  lists; ``0``/``0.0``/``False``/empty containers, the remaining ``{}`` of an
  all-empty record, list order and element position are preserved. Scalar
  ``null`` items inside arrays are positional values and stay in place.
- ``_meta.null_stripped_fields`` (added only when something was stripped)
  lists the dotted paths dropped because of null values — nested dicts extend
  the path with a dot, dicts inside lists with ``[]`` (e.g. ``rows[].bid``) —
  so consumers can tell "value is null" apart from "field absent".
- ``_schema`` maps field names to short descriptions taken from the finance
  Data model behind the command; fields without a usable description fall
  back to the field name, and extra keys observed in the final records are
  described by their own name. Dynamic-field commands (free SQL) omit it.
- ``_meta`` keeps the current summary semantics with the same cleaning
  applied (``0``/``False`` protected).

Everything here is non-mutating: inputs are never modified.
"""

from __future__ import annotations

import typing
from functools import lru_cache
from typing import Any

# Record-level metadata key (intraday partial-bar warning); kept verbatim
# during cleaning and given a fixed schema description when present.
RECORD_META_KEY = "_meta"
RECORD_META_DESCRIPTION = "Record-level metadata (e.g. intraday partial-bar warning)."


def clean_output_value(value: Any, *, keep_empty_strings: bool = False) -> Any:
    """Recursively clean a JSON-like value without touching the input."""
    if isinstance(value, dict):
        return clean_output_record(value, keep_empty_strings=keep_empty_strings)
    if isinstance(value, list):
        return [clean_output_value(item, keep_empty_strings=keep_empty_strings) for item in value]
    return value


def clean_output_record(record: dict[str, Any], *, keep_empty_strings: bool = False) -> dict[str, Any]:
    """Drop ``None`` and exact-``""`` fields; keep ``0``/``False``/empty containers.

    Nested dicts and dicts inside lists are cleaned recursively; scalar list
    items (including nulls, which are positional values) pass through. The
    record-level ``_meta`` entry (intraday warning) is kept verbatim. An
    all-empty record cleans to ``{}`` and stays in place.
    """
    cleaned: dict[str, Any] = {}
    for key, value in record.items():
        if key == RECORD_META_KEY:
            cleaned[key] = value
            continue
        if value is None:
            continue
        if not keep_empty_strings and isinstance(value, str) and value == "":
            continue
        cleaned[key] = clean_output_value(value, keep_empty_strings=keep_empty_strings)
    return cleaned


@lru_cache(maxsize=128)
def finance_data_model(model_name: str) -> type:
    """Resolve the finance Data model class behind an OpenBB model name.

    ProviderInterface return annotations are OBBject generics over
    ``list[Annotated[Data, Tag, ...]]``; multi-provider models annotate a
    Union of tagged branches, of which the ``finance`` one is selected.
    Resolution failures are implementation/registration errors and propagate
    to the caller's structured error path.
    """
    from openbb_core.app.provider_interface import ProviderInterface

    obbject_cls = ProviderInterface().return_annotations[model_name]
    annotation: Any = None
    for base in obbject_cls.__mro__:
        args = getattr(base, "__pydantic_generic_metadata__", {}).get("args") or ()
        if args:
            annotation = args[0]
            break
    if annotation is None:
        raise ValueError(f"model has no generic return annotation: {model_name}")
    if typing.get_origin(annotation) is list:
        annotation = typing.get_args(annotation)[0]
    annotated_args = typing.get_args(annotation)
    data = annotated_args[0] if annotated_args else annotation
    if typing.get_origin(data) is typing.Union:
        for branch in typing.get_args(data):
            branch_args = typing.get_args(branch)
            tag = getattr(branch_args[1], "tag", None) if len(branch_args) > 1 else None
            if tag == "finance":
                return branch_args[0]
        raise ValueError(f"model has no finance data branch: {model_name}")
    return data


@lru_cache(maxsize=128)
def model_field_descriptions(model_name: str) -> dict[str, str]:
    """Field name -> description for a model; missing descriptions use the name."""
    descriptions: dict[str, str] = {}
    for field_name, field in finance_data_model(model_name).model_fields.items():
        description = (field.description or "").strip()
        descriptions[field_name] = description or field_name
    return descriptions


def build_schema(model_name: str, records: list[dict[str, Any]]) -> dict[str, str]:
    """Static model descriptions plus the extra keys of the final records.

    The static part is the complete model field set, including fields that
    are null throughout this result. Extra keys are collected only from the
    final (post-limit) records so limit-truncated data stays out, and fall
    back to their own name. The cached model mapping is copied before
    extension so extra keys never leak across queries.
    """
    schema = dict(model_field_descriptions(model_name))
    if any(RECORD_META_KEY in record for record in records):
        schema[RECORD_META_KEY] = RECORD_META_DESCRIPTION
    for record in records:
        for key in record:
            if key not in schema:
                schema[key] = key
    return schema


def _collect_null_paths(value: Any, path: str, out: set[str]) -> None:
    """Collect dotted paths of ``None`` fields that cleaning will drop.

    Nested dicts extend the path with a dot; dicts inside lists extend it
    with ``[]`` (e.g. ``rows[].bid``), applied per list level so doubly
    nested lists report ``outer[][].key``. Scalar list items are skipped:
    nulls inside arrays are positional values and cleaning keeps them in
    place. The record-level ``_meta`` entry is preserved verbatim by
    cleaning and therefore excluded.
    """
    if isinstance(value, dict):
        for key, item in value.items():
            if key == RECORD_META_KEY:
                continue
            child = f"{path}.{key}" if path else key
            if item is None:
                out.add(child)
            else:
                _collect_null_paths(item, child, out)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                _collect_null_paths(item, f"{path}[]", out)


def null_stripped_fields(records: list[dict[str, Any]]) -> list[str]:
    """Sorted union of dotted paths dropped from *records* due to null values.

    Empty when nothing was stripped; feeds ``_meta.null_stripped_fields`` so
    consumers can tell "value is null" apart from "field absent".
    """
    paths: set[str] = set()
    for record in records:
        _collect_null_paths(record, "", paths)
    return sorted(paths)


def build_success_envelope(
    records: list[dict[str, Any]],
    *,
    model_name: str | None,
    meta: dict[str, Any] | None = None,
    keep_empty_strings: bool = False,
) -> dict[str, Any]:
    """Assemble ``{results, _schema?, _meta?}`` for a successful data query.

    ``model_name=None`` omits ``_schema`` (dynamic-field commands).
    ``keep_empty_strings`` preserves exact-``""`` values (free-SQL dynamic
    columns may produce meaningful empty strings). ``meta`` keeps current
    semantics with the same null cleaning (``0``/``False`` protected).
    ``null_stripped_fields`` is appended to ``_meta`` only when some null
    field was actually stripped; commands without meta and without stripped
    fields keep the meta-less envelope shape.
    """
    envelope: dict[str, Any] = {
        "results": [clean_output_record(record, keep_empty_strings=keep_empty_strings) for record in records]
    }
    if model_name is not None:
        envelope["_schema"] = build_schema(model_name, records)
    stripped = null_stripped_fields(records)
    if meta is not None or stripped:
        merged: dict[str, Any] = dict(meta) if meta is not None else {}
        if stripped:
            merged["null_stripped_fields"] = stripped
        envelope["_meta"] = clean_output_record(merged)
    return envelope
