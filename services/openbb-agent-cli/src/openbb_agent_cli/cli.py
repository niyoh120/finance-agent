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


def _resolve_route(route: str) -> Callable[..., Any]:
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


@app.command(name="index.price.historical")
def index_price_historical(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    """Get index historical price data."""
    _run_route("index.price.historical", symbol=symbol, start_date=start_date, end_date=end_date)


@app.command(name="etf.historical")
def etf_historical(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    """Get ETF historical price data."""
    _run_route("etf.historical", symbol=symbol, start_date=start_date, end_date=end_date)


@app.command(name="economy.calendar")
def economy_calendar(
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    """Get economic calendar events."""
    _run_route("economy.calendar", start_date=start_date, end_date=end_date)


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
