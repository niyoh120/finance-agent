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


def _run_route(route: str, **params: Any) -> None:
    try:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            command = _resolve_route(route)
            result = command(provider="finance", **_drop_none(params))
        _print_json(result.model_dump(mode="json").get("results", []))
    except Exception as exc:
        _print_json({"error": str(exc), "code": _error_code(exc)})
        raise SystemExit(1) from exc


def _run_provider_model(
    model_name: str,
    standard_params: dict[str, Any] | None = None,
    extra_params: dict[str, Any] | None = None,
) -> None:
    import asyncio

    async def _execute() -> None:
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

        _print_json([item.model_dump(mode="json") for item in result])

    try:
        asyncio.run(_execute())
    except Exception as exc:
        _print_json({"error": str(exc), "code": _error_code(exc)})
        raise SystemExit(1) from exc


@app.command(name="equity.price.historical")
def equity_price_historical(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    interval: str = "1d",
    adjusted: bool = False,
) -> None:
    """Get equity historical price data."""
    _run_route(
        "equity.price.historical",
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        interval=interval,
        adjusted=adjusted,
    )


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
) -> None:
    """Screen equities with custom filters.

    Simple filters: Use individual parameters like --price-min, --volume-min.

    Advanced filters: Use --filters with JSON string for arbitrary StockField filtering.
    Example: --filters '{"MACD_LEVEL_12_26": {"min": 0}, "YEAR_BETA_1": {"max": 1.5}}'

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
) -> None:
    """Get index historical price data."""
    _run_route("index.price.historical", symbol=symbol, start_date=start_date, end_date=end_date)


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
) -> None:
    """Get ETF historical price data."""
    _run_route("etf.historical", symbol=symbol, start_date=start_date, end_date=end_date)


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
