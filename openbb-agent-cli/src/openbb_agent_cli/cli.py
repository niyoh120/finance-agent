"""Agent-friendly JSON CLI for the OpenBB finance provider."""

from __future__ import annotations

import contextlib
import io
import json
from collections.abc import Callable
from typing import Any, Literal

from cyclopts import App
from cyclopts.exceptions import CycloptsError

from openbb_agent_cli import __version__

app = App(name="openbb-agent-cli", version=__version__, help="Agent-friendly JSON CLI for openbb-finance.")


def _json_default(value: Any) -> str:
    return str(value)


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, default=_json_default, separators=(",", ":")))


def _drop_none(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if value is not None}


def _apply_limit(results: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    """Return the last *limit* items preserving order; pass through when limit is None."""
    if limit is None:
        return results
    if limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit}")
    return results[-limit:]


def _ensure_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [str(value)]


def _inject_obbject_types() -> None:
    """Inject OBBject_* types into provider_interface module for openbb compatibility."""
    import openbb_core.app.provider_interface as pi_module
    from openbb_core.app.provider_interface import ProviderInterface

    pi = ProviderInterface()
    for name, cls in pi.return_annotations.items():
        setattr(pi_module, f"OBBject_{name}", cls)


def _resolve_route(route: str) -> Callable[..., Any]:
    _inject_obbject_types()
    from openbb import obb

    target: Any = obb
    for part in route.split("."):
        target = getattr(target, part)
    return target


def _error_code(exc: Exception) -> str:
    name = exc.__class__.__name__
    if name == "EmptyDataError":
        return "EMPTY_DATA"
    if isinstance(exc, CycloptsError):
        return "CLI_ERROR"
    return name.upper()


def _execute_route(route: str, **params: Any) -> list[dict[str, Any]]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        command = _resolve_route(route)
        result = command(provider="finance", **_drop_none(params))
    return result.model_dump(mode="json").get("results", [])


def _run_route(route: str, **params: Any) -> None:
    try:
        _print_json(_execute_route(route, **params))
    except Exception as exc:
        _print_json({"error": str(exc), "code": _error_code(exc)})
        raise SystemExit(1) from exc


def _execute_provider_model(
    model_name: str,
    standard_params: dict[str, Any] | None = None,
    extra_params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    import asyncio

    async def _execute() -> list[dict[str, Any]]:
        from openbb_core.app.model.command_context import CommandContext
        from openbb_core.app.provider_interface import ProviderInterface
        from openbb_core.app.query import Query

        _inject_obbject_types()
        pi = ProviderInterface()
        provider_choices = pi.model_providers[model_name](provider="finance")
        standard = pi.params[model_name]["standard"](**_drop_none(standard_params or {}))
        extra = pi.params[model_name]["extra"](**(extra_params or {}))
        query_obj = Query(CommandContext(), provider_choices, standard, extra)

        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = await query_obj.execute()

        return [item.model_dump(mode="json") for item in result]

    return asyncio.run(_execute())


def _run_provider_model(
    model_name: str,
    standard_params: dict[str, Any] | None = None,
    extra_params: dict[str, Any] | None = None,
) -> None:
    try:
        _print_json(_execute_provider_model(model_name, standard_params, extra_params))
    except Exception as exc:
        _print_json({"error": str(exc), "code": _error_code(exc)})
        raise SystemExit(1) from exc


RouteExecutor = Callable[[dict[str, Any]], list[dict[str, Any]]]


def _route_executor(route: str) -> RouteExecutor:
    return lambda params: _execute_route(route, **params)


def _provider_executor(model_name: str) -> RouteExecutor:
    return lambda params: _execute_provider_model(model_name, params)


_HISTORICAL_ROUTES = {
    "equity.price.historical": {"interval": "1d", "adjusted": False},
    "index.price.historical": {},
    "etf.historical": {},
}

_ROUTE_LIMIT_KEY = "__cli_limit__"


def _historical_executor(route: str) -> RouteExecutor:
    """Execute a historical route, applying CLI-side limit if provided in params."""
    defaults = _HISTORICAL_ROUTES[route]

    def _exec(params: dict[str, Any]) -> list[dict[str, Any]]:
        limit = params.pop(_ROUTE_LIMIT_KEY, None)
        route_params = {**defaults, **params}
        results = _execute_route(route, **route_params)
        return _apply_limit(results, limit)

    return _exec


def _index_snapshots_executor(params: dict[str, Any]) -> list[dict[str, Any]]:
    return _execute_provider_model(
        "IndexSnapshots",
        {"region": params.get("region", "cn")},
        {"symbol": _ensure_list(params.get("symbol"))},
    )


COMMAND_EXECUTORS: dict[str, RouteExecutor] = {
    "equity.price.historical": _historical_executor("equity.price.historical"),
    "equity.price.quote": _route_executor("equity.price.quote"),
    "equity.search": _route_executor("equity.search"),
    "equity.screener": _route_executor("equity.screener"),
    "index.available": _route_executor("index.available"),
    "index.search": _route_executor("index.search"),
    "index.price.historical": _historical_executor("index.price.historical"),
    "index.snapshots": _index_snapshots_executor,
    "etf.historical": _historical_executor("etf.historical"),
    "etf.search": _provider_executor("EtfSearch"),
    "economy.calendar": _route_executor("economy.calendar"),
    "economy.available-indicators": _route_executor("economy.available_indicators"),
    "economy.indicators": _route_executor("economy.indicators"),
    "economy.gdp.nominal": _route_executor("economy.gdp.nominal"),
    "economy.cpi": _route_executor("economy.cpi"),
    "news.company": _route_executor("news.company"),
    "news.world": _route_executor("news.world"),
    "derivatives.options.unusual": _route_executor("derivatives.options.unusual"),
}


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
                "params": {"symbol": symbol, "start_date": start_date, "end_date": end_date, "__cli_limit__": params.get("limit")},
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
                "params": {"market": market_by_region.get(region, region), "limit": params.get("limit", 20)},
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
                "params": {"symbol": symbol, "start_date": start_date, "end_date": end_date, "__cli_limit__": params.get("limit")},
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


@app.command(name="equity.price.historical")
def equity_price_historical(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    interval: str = "1d",
    adjusted: bool = False,
    limit: int | None = None,
) -> None:
    """Get equity historical price data."""
    try:
        results = _execute_route(
            "equity.price.historical",
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
            adjusted=adjusted,
        )
        _print_json(_apply_limit(results, limit))
    except Exception as exc:
        _print_json({"error": str(exc), "code": _error_code(exc)})
        raise SystemExit(1) from exc


@app.command(name="equity.price.quote")
def equity_price_quote(symbol: str) -> None:
    """Get an equity quote."""
    _run_route("equity.price.quote", symbol=symbol)


@app.command(name="equity.search")
def equity_search(query: str, is_symbol: bool = False) -> None:
    """Search equities."""
    _run_route("equity.search", query=query, is_symbol=is_symbol)


@app.command(name="equity.screener")
def equity_screener(
    market: Literal["america", "hongkong", "china", "global"] | None = None,
    limit: int = 150,
    # Simple filters
    price_min: float | None = None,
    price_max: float | None = None,
    change_percent_min: float | None = None,
    change_percent_max: float | None = None,
    volume_min: int | None = None,
    volume_max: int | None = None,
    market_cap_min: float | None = None,
    market_cap_max: float | None = None,
    rsi_min: float | None = None,
    rsi_max: float | None = None,
    sector: list[str] | None = None,
    # Advanced filters (JSON string)
    filters: str | None = None,
    fields: str | None = None,
) -> None:
    """Screen equities with custom filters.

    Simple filters: Use individual parameters like --price-min, --volume-min.

    Advanced filters: Use --filters with JSON string for arbitrary StockField filtering.
    Example: --filters '{"MACD_LEVEL_12_26": {"min": 0}, "YEAR_BETA_1": {"max": 1.5}}'

    Custom fields: Use --fields with JSON array string to control returned StockFields.
    Example: --fields '["SYMBOL", "NAME", "PRICE", "MACD_LEVEL_12_26"]'

    Available StockFields (3526 total): PRICE, VOLUME, MARKET_CAPITALIZATION, CHANGE_PERCENT,
    RELATIVE_STRENGTH_INDEX_14, MACD_LEVEL_12_26, YEAR_BETA_1, EMA_20, SMA_50, PE_RATIO_TTM,
    EPS_DILUTED_TTM, DIVIDEND_YIELD, DEBT_TO_EQUITY, etc.

    Use tvscreener.StockField.search("keyword") to find specific fields.
    """
    _run_route(
        "equity.screener",
        market=market,
        limit=limit,
        price_min=price_min,
        price_max=price_max,
        change_percent_min=change_percent_min,
        change_percent_max=change_percent_max,
        volume_min=volume_min,
        volume_max=volume_max,
        market_cap_min=market_cap_min,
        market_cap_max=market_cap_max,
        rsi_min=rsi_min,
        rsi_max=rsi_max,
        sector=_ensure_list(sector),
        filters=filters,
        fields=fields,
    )


@app.command(name="index.available")
def index_available() -> None:
    """Get available indices."""
    _run_route("index.available")


@app.command(name="index.search")
def index_search(query: str, is_symbol: bool = False) -> None:
    """Search indices."""
    _run_route("index.search", query=query, is_symbol=is_symbol)


@app.command(name="index.price.historical")
def index_price_historical(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = None,
) -> None:
    """Get index historical price data."""
    try:
        results = _execute_route("index.price.historical", symbol=symbol, start_date=start_date, end_date=end_date)
        _print_json(_apply_limit(results, limit))
    except Exception as exc:
        _print_json({"error": str(exc), "code": _error_code(exc)})
        raise SystemExit(1) from exc


@app.command(name="index.snapshots")
def index_snapshots(
    region: Literal["cn", "us", "hk"] = "cn",
    symbol: list[str] | None = None,
) -> None:
    """Get index snapshots.

    Args:
        region: Market region - cn (China), us (US), or hk (Hong Kong).
        symbol: Optional list of index symbols to fetch. If not provided, returns default indices for the region.
    """
    _run_provider_model("IndexSnapshots", {"region": region}, {"symbol": _ensure_list(symbol)})


@app.command(name="etf.historical")
def etf_historical(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = None,
) -> None:
    """Get ETF historical price data."""
    try:
        results = _execute_route("etf.historical", symbol=symbol, start_date=start_date, end_date=end_date)
        _print_json(_apply_limit(results, limit))
    except Exception as exc:
        _print_json({"error": str(exc), "code": _error_code(exc)})
        raise SystemExit(1) from exc


@app.command(name="etf.search")
def etf_search(query: str) -> None:
    """Search ETFs."""
    _run_provider_model("EtfSearch", {"query": query})


@app.command(name="economy.calendar")
def economy_calendar(
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    """Get economic calendar events."""
    _run_route("economy.calendar", start_date=start_date, end_date=end_date)


@app.command(name="economy.available-indicators")
def economy_available_indicators() -> None:
    """Get available economic indicators."""
    _run_route("economy.available_indicators")


@app.command(name="economy.indicators")
def economy_indicators(
    symbol: str,
    country: str = "china",
    frequency: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    """Get economic indicators data."""
    _run_route(
        "economy.indicators",
        symbol=symbol,
        country=country,
        frequency=frequency,
        start_date=start_date,
        end_date=end_date,
    )


@app.command(name="economy.gdp.nominal")
def economy_gdp_nominal(
    country: str = "china",
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    """Get nominal GDP data."""
    _run_route(
        "economy.gdp.nominal",
        country=country,
        start_date=start_date,
        end_date=end_date,
    )


@app.command(name="economy.cpi")
def economy_cpi(
    country: str = "china",
    transform: Literal["index", "yoy", "period"] | None = None,
    frequency: Literal["annual", "quarter", "monthly"] = "monthly",
    harmonized: bool = False,
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    """Get Consumer Price Index data."""
    _run_route(
        "economy.cpi",
        country=country,
        transform=transform,
        frequency=frequency,
        harmonized=harmonized,
        start_date=start_date,
        end_date=end_date,
    )


@app.command(name="news.company")
def news_company(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 100,
) -> None:
    """Get company news."""
    _run_route("news.company", symbol=symbol, start_date=start_date, end_date=end_date, limit=limit)


@app.command(name="news.world")
def news_world(
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 100,
) -> None:
    """Get world news."""
    _run_route("news.world", start_date=start_date, end_date=end_date, limit=limit)


@app.command(name="derivatives.options.unusual")
def derivatives_options_unusual(
    symbol: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    side: Literal["Bid", "Ask"] | None = None,
    option_type: Literal["P", "C"] | None = None,
    min_premium: float | None = None,
    min_vol_oi: float | None = None,
    limit: int = 50,
) -> None:
    """Get unusual options flow records."""
    _run_route(
        "derivatives.options.unusual",
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        side=side,
        option_type=option_type,
        min_premium=min_premium,
        min_vol_oi=min_vol_oi,
        limit=limit,
    )


@app.command(name="batch")
def batch(
    queries: str | None = None,
    template: Literal["equity-overview", "market-overview", "macro-overview", "index-detail"] | None = None,
    symbol: str | None = None,
    region: Literal["cn", "us", "hk"] = "cn",
    country: str = "china",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 20,
    news_limit: int = 20,
    options_limit: int = 50,
    max_workers: int = 4,
) -> None:
    """Run multiple finance queries in one JSON response."""
    try:
        parsed_queries = _parse_batch_queries(
            queries,
            template,
            {
                "symbol": symbol,
                "region": region,
                "country": country,
                "start_date": start_date,
                "end_date": end_date,
                "limit": limit,
                "news_limit": news_limit,
                "options_limit": options_limit,
            },
        )
        _print_json(_run_batch_queries(parsed_queries, max_workers))
    except Exception as exc:
        _print_json({"error": str(exc), "code": _error_code(exc)})
        raise SystemExit(1) from exc


def main() -> None:
    """Run the CLI."""
    try:
        app(exit_on_error=False, print_error=False)
    except CycloptsError as exc:
        _print_json({"error": str(exc), "code": _error_code(exc)})
        raise SystemExit(2) from exc
    except KeyboardInterrupt:
        _print_json({"error": "Interrupted", "code": "INTERRUPTED"})
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
