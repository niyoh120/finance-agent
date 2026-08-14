"""Batch query templating and execution for the agent CLI.

Turns a template name (or a raw JSON query list) into a list of
``{name, command, params}`` queries and runs them through
``COMMAND_EXECUTORS``, collecting per-query results and errors.
"""

from __future__ import annotations

import json
from typing import Any

from .executors import COMMAND_EXECUTORS, _error_code


def _build_template_queries(template: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    symbol = params.get("symbol")
    region = params.get("region", "cn")
    country = params.get("country", "china")
    start_date = params.get("start_date")
    end_date = params.get("end_date")

    if template == "equity-overview":
        if not symbol:
            raise ValueError("template equity-overview requires symbol")
        return [
            {"name": "quote", "command": "equity.price.quote", "params": {"symbol": symbol}},
            {
                "name": "historical",
                "command": "equity.price.historical",
                "params": {
                    "symbol": symbol,
                    "start_date": start_date,
                    "end_date": end_date,
                    "__cli_limit__": params.get("limit"),
                },
            },
            {
                "name": "news",
                "command": "news.company",
                "params": {
                    "symbol": symbol,
                    "start_date": start_date,
                    "end_date": end_date,
                    "limit": params.get("news_limit", 20),
                },
            },
            {
                "name": "options",
                "command": "derivatives.options.unusual",
                "params": {
                    "symbol": symbol,
                    "start_date": start_date,
                    "end_date": end_date,
                    "limit": params.get("options_limit", 50),
                },
            },
        ]

    if template == "market-overview":
        market_by_region = {"cn": "china", "us": "america", "hk": "hongkong"}
        return [
            {"name": "indices", "command": "index.snapshots", "params": {"region": region}},
            {
                "name": "movers",
                "command": "equity.screener",
                "params": {
                    "market": market_by_region.get(region, region),
                    "volume_min": 1,
                    "limit": params.get("limit", 20),
                },
            },
            {
                "name": "news",
                "command": "news.world",
                "params": {
                    "start_date": start_date,
                    "end_date": end_date,
                    "limit": params.get("news_limit", 20),
                },
            },
        ]

    if template == "macro-overview":
        return [
            {
                "name": "gdp",
                "command": "economy.gdp.nominal",
                "params": {"country": country, "start_date": start_date, "end_date": end_date},
            },
            {
                "name": "cpi",
                "command": "economy.cpi",
                "params": {
                    "country": country,
                    "transform": "yoy",
                    "start_date": start_date,
                    "end_date": end_date,
                },
            },
            {
                "name": "pmi",
                "command": "economy.indicators",
                "params": {"symbol": "PMI", "country": country, "start_date": start_date, "end_date": end_date},
            },
            {
                "name": "calendar",
                "command": "economy.calendar",
                "params": {"start_date": start_date, "end_date": end_date},
            },
        ]

    if template == "index-detail":
        if not symbol:
            raise ValueError("template index-detail requires symbol")
        return [
            {"name": "snapshot", "command": "index.snapshots", "params": {"region": region, "symbol": symbol}},
            {
                "name": "historical",
                "command": "index.price.historical",
                "params": {
                    "symbol": symbol,
                    "start_date": start_date,
                    "end_date": end_date,
                    "__cli_limit__": params.get("limit"),
                },
            },
        ]

    raise ValueError(f"Unknown batch template: {template}")


def _parse_batch_queries(
    queries: str | None,
    template: str | None,
    template_params: dict[str, Any],
) -> list[dict[str, Any]]:
    if template:
        return _build_template_queries(template, template_params)
    if queries is None:
        raise ValueError("Either queries or template is required")

    parsed = json.loads(queries)
    if not isinstance(parsed, list):
        raise ValueError("queries must be a JSON array")
    return parsed


def _execute_batch_query(
    index: int,
    query: dict[str, Any],
) -> tuple[str, list[dict[str, Any]] | None, dict[str, str] | None]:
    name = str(query.get("name") or index)
    command = query.get("command")
    params = query.get("params", {})

    try:
        if not isinstance(command, str):
            raise ValueError("query command must be a string")
        if not isinstance(params, dict):
            raise ValueError("query params must be an object")
        executor = COMMAND_EXECUTORS.get(command)
        if executor is None:
            raise ValueError(f"Unsupported batch command: {command}")
        return name, executor(params), None
    except Exception as exc:
        return name, None, {"error": str(exc), "code": _error_code(exc)}


def _run_batch_queries(queries: list[dict[str, Any]], max_workers: int) -> dict[str, Any]:
    results: dict[str, Any] = {}
    errors: dict[str, dict[str, str]] = {}
    _ = max_workers

    for index, query in enumerate(queries):
        if not isinstance(query, dict):
            errors[str(index)] = {"error": "query must be an object", "code": "VALUEERROR"}
            continue

        name, data, error = _execute_batch_query(index, query)
        if error is None:
            results[name] = data
        else:
            errors[name] = error

    return {"results": results, "errors": errors}
