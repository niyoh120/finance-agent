"""Agent-friendly JSON CLI for the OpenBB finance provider."""

from __future__ import annotations

import contextlib
import io
import json
from collections.abc import Callable
from dataclasses import is_dataclass
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from cyclopts import App
from cyclopts.exceptions import CycloptsError

from openbb_finance.sources.symbols import infer_market_from_symbol

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


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_NEW_YORK = ZoneInfo("America/New_York")


def _is_market_open(market: str) -> bool:
    """Best-effort check whether *market* (cn/hk/us) is currently in its regular session.

    Holidays and early-close days are ignored: an early-close session still has partial
    data, and on a holiday the source returns no same-day row at all, so neither case
    produces a false positive for the "latest bar may be intraday" warning.
    """
    # Weekend is checked in the exchange-local timezone, because the US session spans
    # past Beijing midnight (e.g. Friday evening ET is Saturday morning in Shanghai).
    if market == "us":
        now = datetime.now(_NEW_YORK)
        if now.weekday() >= 5:
            return False
        minutes = now.hour * 60 + now.minute
        return 9 * 60 + 30 <= minutes < 16 * 60

    now_bj = datetime.now(_SHANGHAI)
    if now_bj.weekday() >= 5:
        return False

    def _in(start_h: int, start_m: int, end_h: int, end_m: int) -> bool:
        minutes = now_bj.hour * 60 + now_bj.minute
        return start_h * 60 + start_m <= minutes < end_h * 60 + end_m

    if market == "cn":
        return _in(9, 30, 11, 30) or _in(13, 0, 15, 0)
    if market == "hk":
        return _in(9, 30, 12, 0) or _in(13, 0, 16, 0)
    return False


def _tag_intraday_last_bar(symbol: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate the last bar with `_meta` when the market is open and that bar is today.

    Non-intraday case is a full pass-through: no key added, no copy made. The annotation
    is attached to the triggering record so consumers reading that bar see the caveat in
    place (e.g. volume is a partial-session cumulative, not a full day).
    """
    if not results:
        return results
    market = infer_market_from_symbol(symbol)
    if not _is_market_open(market):
        return results
    last = results[-1]
    last_date = str(last.get("date", ""))[:10]
    # Compare against the exchange-local calendar date: a US daily bar is dated by the
    # US trading day, which is one Beijing day behind during the cross-midnight session.
    now_tz = _NEW_YORK if market == "us" else _SHANGHAI
    if last_date != datetime.now(now_tz).date().isoformat():
        return results
    # ponytail: shallow-copy only the tagged bar so callers keep their own list intact
    tagged = [{**last, "_meta": {
        "warning": "market is currently open; this bar may be a partial-session snapshot, OHLCV not final",
        "market": market,
    }}]
    return results[:-1] + tagged


def _ensure_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [str(value)]


def _coalesce(value: Any, default: Any) -> Any:
    return default if value is None else value


def _inject_obbject_types() -> None:
    """Inject OBBject_* types into provider_interface module for openbb compatibility."""
    import openbb_core.app.provider_interface as pi_module
    from openbb_core.app.provider_interface import ProviderInterface

    pi = ProviderInterface()
    for name, cls in pi.return_annotations.items():
        setattr(pi_module, f"OBBject_{name}", cls)


ROUTE_MODELS = {
    "equity.price.historical": "EquityHistorical",
    "equity.price.quote": "EquityQuote",
    "equity.search": "EquitySearch",
    "equity.screener": "EquityScreener",
    "index.available": "AvailableIndices",
    "index.search": "IndexSearch",
    "index.price.historical": "IndexHistorical",
    "etf.historical": "EtfHistorical",
    "etf.holdings": "EtfHoldings",
    "etf.sectors": "EtfSectors",
    "economy.calendar": "EconomicCalendar",
    "economy.available_indicators": "AvailableIndicators",
    "economy.indicators": "EconomicIndicators",
    "economy.gdp.nominal": "GdpNominal",
    "economy.cpi": "ConsumerPriceIndex",
    "news.company": "CompanyNews",
    "news.world": "WorldNews",
    "derivatives.options.unusual": "OptionsUnusual",
    "derivatives.options.chain": "OptionsChain",
    "derivatives.options.historical": "OptionsHistorical",
    "derivatives.options.daily": "OptionsDaily",
    "stocks.fundamental.income": "IncomeStatement",
    "stocks.fundamental.balance": "BalanceSheetStatement",
    "stocks.fundamental.cash": "CashFlowStatement",
    "stocks.fundamental.ratios": "FinancialRatios",
    "stocks.estimates": "AnalystEstimates",
    "stocks.insider_trading": "InsiderTrading",
    "government.trades": "GovernmentTrades",
    "stocks.filings": "CompanyFilings",
}


def _error_code(exc: Exception) -> str:
    name = exc.__class__.__name__
    if name == "EmptyDataError":
        return "EMPTY_DATA"
    if isinstance(exc, CycloptsError):
        return "CLI_ERROR"
    return name.upper()


def _split_standard_extra(model_name: str, params: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split params into standard vs extra based on the model's standard fields.

    Custom ConvexValue models add fields (period, multiplier, etc.) to the
    QueryParams subclass that the OpenBB standard model does not declare; the
    dynamic API wrapper only sees the standard fields, so those extras end up
    untyped and default to Query(...). Route them through extra_params instead.
    """
    from openbb_core.app.provider_interface import ProviderInterface

    pi = ProviderInterface()
    std_cls = pi.params[model_name]["standard"]
    model_fields = getattr(std_cls, "model_fields", None)
    standard_names = set(model_fields if model_fields is not None else std_cls.__annotations__)
    standard: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        (standard if key in standard_names else extra)[key] = value
    return standard, extra


def _execute_route(route: str, **params: Any) -> list[dict[str, Any]]:
    return _execute_provider_model(ROUTE_MODELS[route], params)


def _run_route(route: str, **params: Any) -> None:
    try:
        _print_json(_execute_route(route, **params))
    except Exception as exc:
        _print_json({"error": str(exc), "code": _error_code(exc)})
        raise SystemExit(1) from exc


def _run_cv_route(route: str, **params: Any) -> None:
    """Run a ConvexValue-backed route, splitting standard vs extra params.

    CV models subclass an OpenBB standard QueryParams and add provider-specific
    fields (period, multiplier, date, etc.). The dynamic API layer only sees
    the standard fields, so extras must go through extra_params to avoid the
    Query(...) default injection. See _split_standard_extra.
    """
    try:
        standard, extra = _split_standard_extra(ROUTE_MODELS[route], params)
        _print_json(_execute_provider_model(ROUTE_MODELS[route], standard, extra))
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
        standard_cls = pi.params[model_name]["standard"]
        extra_cls = pi.params[model_name]["extra"]
        model_fields = getattr(standard_cls, "model_fields", None)
        standard_fields = set(model_fields if model_fields is not None else standard_cls.__annotations__)
        if extra_params is None:
            params = _drop_none(standard_params or {})
            standard_values = {key: value for key, value in params.items() if key in standard_fields}
            extra_values = {key: value for key, value in params.items() if key not in standard_fields}
        else:
            standard_values = _drop_none(standard_params or {})
            extra_values = extra_params if is_dataclass(extra_cls) else _drop_none(extra_params or {})
        standard = standard_cls(**standard_values)
        extra = extra_cls(**extra_values)
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


def _filter_sort_limit(
    records: list[dict[str, Any]],
    *,
    filters: dict[str, Any] | None = None,
    sort_by: str | None = None,
    sort_dir: Literal["asc", "desc"] = "asc",
    limit: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply local filter/sort/limit and return (records, meta).

    meta always includes `returned`. When sort_by is set it is echoed. When the
    limit truncates, `truncated=True` and `filtered` reports the pre-limit size
    so the caller can decide whether to raise the limit. `total` is included
    only when provided by the caller (server-reported total).
    """
    filtered = list(records)
    if filters:
        for key, expected in filters.items():
            if expected is None:
                continue
            filtered = [r for r in filtered if r.get(key) == expected]
    if sort_by:
        # Sort with None always last (regardless of direction): split None rows,
        # sort the rest, then append None rows at the end.
        with_value = [r for r in filtered if r.get(sort_by) is not None]
        without_value = [r for r in filtered if r.get(sort_by) is None]
        with_value.sort(key=lambda r: r.get(sort_by), reverse=(sort_dir == "desc"))
        filtered = with_value + without_value
    pre_limit = len(filtered)
    if limit is not None and limit > 0:
        filtered = filtered[:limit]
    meta: dict[str, Any] = {"returned": len(filtered), "filtered": pre_limit}
    if sort_by:
        meta["sort_by"] = sort_by
        meta["sort_dir"] = sort_dir
    if limit is not None and limit > 0 and len(filtered) < pre_limit:
        meta["truncated"] = True
    return filtered, meta


def _print_results_with_meta(
    records: list[dict[str, Any]],
    meta: dict[str, Any],
    total: int | None = None,
) -> None:
    payload: dict[str, Any] = {"results": records, "_meta": meta}
    if total is not None:
        payload["_meta"]["total"] = total
    _print_json(payload)


def _run_cv_list(
    model_name: str,
    *,
    standard_params: dict[str, Any] | None = None,
    extra_params: dict[str, Any] | None = None,
    sort_by: str | None = None,
    sort_dir: Literal["asc", "desc"] = "desc",
    limit: int | None = None,
    date_fields: tuple[str, ...] = ("date", "period_ending", "filing_date", "transaction_date", "filingDate", "transactionDate", "date"),
) -> None:
    """Run a ConvexValue list-returning model and wrap output as {results, _meta}.

    Fetches via _execute_provider_model (which returns list[dict]), then applies
    local sort + limit. _meta reports returned/filtered/sort info; FMP endpoints
    do not expose a server total so `total` is omitted (the caller can infer
    "there may be more" from filtered > returned).
    """
    try:
        records = _execute_provider_model(model_name, standard_params, extra_params)
        # Normalize date-like string fields to sortable strings (ISO sorts lexicographically).
        filtered, meta = _filter_sort_limit(
            records, sort_by=sort_by, sort_dir=sort_dir,
            limit=limit,
        )
        _print_results_with_meta(filtered, meta)
    except Exception as exc:
        _print_json({"error": str(exc), "code": _error_code(exc)})
        raise SystemExit(1) from exc


RouteExecutor = Callable[[dict[str, Any]], list[dict[str, Any]]]
TechnicalIndicator = Literal["rsi", "macd", "sma", "ema", "bbands", "atr", "stoch", "vwap"]
_TECHNICAL_INDICATORS = ["rsi", "macd", "sma", "ema", "bbands", "atr", "stoch", "vwap"]


def _route_executor(route: str) -> RouteExecutor:
    return lambda params: _execute_route(route, **params)


def _cv_route_executor(route: str) -> RouteExecutor:
    """Executor for ConvexValue-backed routes that splits standard vs extra params."""
    # Safety defaults: when batch callers omit limit on these list endpoints,
    # cap the result to avoid multi-megabyte payloads. Callers can override
    # by passing an explicit limit (use 0 for chain/historical to mean all).
    default_limit = {
        "derivatives.options.chain": 100,
        "etf.holdings": 20,
        "stocks.insider_trading": 50,
        "government.trades": 50,
        "stocks.filings": 50,
    }.get(route)

    def _exec(params: dict[str, Any]) -> list[dict[str, Any]]:
        explicit_limit = params.get("limit")
        if default_limit is not None and explicit_limit is None:
            params = {"limit": default_limit, **params}
        standard, extra = _split_standard_extra(ROUTE_MODELS[route], params)
        records = _execute_provider_model(ROUTE_MODELS[route], standard, extra)
        # Only apply a local cap when we injected the default; respect an
        # explicit positive limit (and limit=0 meaning "all").
        effective = default_limit if explicit_limit is None else explicit_limit
        if isinstance(effective, int) and effective > 0 and len(records) > effective:
            records = records[:effective]
        return records
    return _exec


def _provider_executor(model_name: str) -> RouteExecutor:
    return lambda params: _execute_provider_model(model_name, params)


_HISTORICAL_ROUTES = {
    "equity.price.historical": {"interval": "1d", "adjusted": False},
    "index.price.historical": {},
    "etf.historical": {},
}

_ROUTE_LIMIT_KEY = "__cli_limit__"


def _historical_executor(route: str) -> RouteExecutor:
    """Execute a historical route, applying CLI-side limit and intraday tagging.

    Both direct commands and the `batch` path route through here for the three
    historical routes, so partial-session tagging stays consistent.
    """
    defaults = _HISTORICAL_ROUTES[route]

    def _exec(params: dict[str, Any]) -> list[dict[str, Any]]:
        limit = params.pop(_ROUTE_LIMIT_KEY, None)
        route_params = {**defaults, **params}
        results = _execute_route(route, **route_params)
        limited = _apply_limit(results, limit)
        symbol = route_params.get("symbol")
        return _tag_intraday_last_bar(symbol, limited) if symbol else limited

    return _exec


def _index_snapshots_executor(params: dict[str, Any]) -> list[dict[str, Any]]:
    return _execute_provider_model(
        "IndexSnapshots",
        {"region": params.get("region", "cn")},
        {"symbol": _ensure_list(params.get("symbol"))},
    )


def _technical_indicators_params(
    *,
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    interval: str | None = None,
    adjusted: bool | None = None,
    indicators: list[str] | None = None,
    rsi_length: int | None = None,
    macd_fast: int | None = None,
    macd_slow: int | None = None,
    macd_signal: int | None = None,
    sma_lengths: list[int] | None = None,
    ema_lengths: list[int] | None = None,
    bbands_length: int | None = None,
    bbands_std: float | None = None,
    atr_length: int | None = None,
    stoch_k: int | None = None,
    stoch_d: int | None = None,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "start_date": start_date,
        "end_date": end_date,
        "interval": _coalesce(interval, "1d"),
        "adjusted": _coalesce(adjusted, False),
        "indicators": _coalesce(_ensure_list(indicators) or None, list(_TECHNICAL_INDICATORS)),
        "rsi_length": _coalesce(rsi_length, 14),
        "macd_fast": _coalesce(macd_fast, 12),
        "macd_slow": _coalesce(macd_slow, 26),
        "macd_signal": _coalesce(macd_signal, 9),
        "sma_lengths": _coalesce(sma_lengths or None, [20, 50]),
        "ema_lengths": _coalesce(ema_lengths or None, [20]),
        "bbands_length": _coalesce(bbands_length, 20),
        "bbands_std": _coalesce(bbands_std, 2.0),
        "atr_length": _coalesce(atr_length, 14),
        "stoch_k": _coalesce(stoch_k, 14),
        "stoch_d": _coalesce(stoch_d, 3),
    }


def _technical_indicators_executor(params: dict[str, Any]) -> list[dict[str, Any]]:
    route_params = dict(params)
    batch_limit = route_params.pop("limit", None)
    limit = route_params.pop(_ROUTE_LIMIT_KEY, batch_limit)
    symbol = route_params.get("symbol")
    if not symbol:
        raise ValueError("technical.indicators requires symbol")
    results = _execute_provider_model(
        "TechnicalIndicators",
        {},
        _technical_indicators_params(
            symbol=symbol,
            start_date=route_params.get("start_date"),
            end_date=route_params.get("end_date"),
            interval=route_params.get("interval"),
            adjusted=route_params.get("adjusted"),
            indicators=route_params.get("indicators"),
            rsi_length=route_params.get("rsi_length"),
            macd_fast=route_params.get("macd_fast"),
            macd_slow=route_params.get("macd_slow"),
            macd_signal=route_params.get("macd_signal"),
            sma_lengths=route_params.get("sma_lengths"),
            ema_lengths=route_params.get("ema_lengths"),
            bbands_length=route_params.get("bbands_length"),
            bbands_std=route_params.get("bbands_std"),
            atr_length=route_params.get("atr_length"),
            stoch_k=route_params.get("stoch_k"),
            stoch_d=route_params.get("stoch_d"),
        ),
    )
    return _apply_limit(results, limit)


def _options_screener_executor(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Execute OptionsScreener via the provider model directly (no standard route)."""
    route_params = dict(params)
    limit = route_params.pop("limit", 50)
    extra = {}
    if "extra_filters" in route_params:
        ef = route_params.pop("extra_filters")
        if isinstance(ef, str):
            import json as _json
            ef = _json.loads(ef)
        extra["extra_filters"] = ef
    return _execute_provider_model(
        "OptionsScreener",
        {},
        {**_drop_none(route_params), "limit": limit, **extra},
    )


def _options_query_executor(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Execute OptionsQuery (free-form SQL) via the provider model directly."""
    return _execute_provider_model(
        "OptionsQuery",
        {},
        {"sql": params["sql"], "max_rows": params.get("max_rows")},
    )


def _options_chain_batch_executor(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Batch executor for options chain: fetch via source, apply limit."""
    import asyncio
    from openbb_finance.models.equity_options_chain import FinanceOptionsChainFetcher
    symbol = params.get("symbol")
    if not symbol:
        return []
    limit = params.get("limit", 100)
    expiration = params.get("expiration")
    option_type = params.get("option_type")

    async def _fetch() -> tuple[list[dict[str, Any]], int]:
        q = FinanceOptionsChainFetcher.transform_query({"symbol": symbol})
        data = await FinanceOptionsChainFetcher.aextract_data(q, None)
        return data.get("records", []), data.get("contract_count", 0)

    records, _ = asyncio.run(_fetch())
    if expiration:
        from datetime import date as _date
        exp = _date.fromisoformat(expiration)
        records = [r for r in records if r.get("expiration") == exp]
    if option_type:
        records = [r for r in records if r.get("option_type") == option_type]
    min_dte = params.get("min_dte")
    max_dte = params.get("max_dte")
    if min_dte is not None:
        records = [r for r in records if r.get("dte") is not None and r["dte"] >= min_dte]
    if max_dte is not None:
        records = [r for r in records if r.get("dte") is not None and r["dte"] <= max_dte]
    records, _ = _filter_sort_limit(
        records,
        sort_by=params.get("sort_by", "open_interest"),
        sort_dir=params.get("sort_dir", "desc"),
        limit=limit if isinstance(limit, int) and limit > 0 else None,
    )
    return records


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
    "technical.indicators": _technical_indicators_executor,
    "news.company": _route_executor("news.company"),
    "news.world": _route_executor("news.world"),
    "derivatives.options.unusual": _route_executor("derivatives.options.unusual"),
    "derivatives.options.chain": _options_chain_batch_executor,
    "derivatives.options.historical": _cv_route_executor("derivatives.options.historical"),
    "derivatives.options.daily": _cv_route_executor("derivatives.options.daily"),
    "etf.holdings": _cv_route_executor("etf.holdings"),
    "etf.sectors": _cv_route_executor("etf.sectors"),
    "stocks.fundamental.income": _cv_route_executor("stocks.fundamental.income"),
    "stocks.fundamental.balance": _cv_route_executor("stocks.fundamental.balance"),
    "stocks.fundamental.cash": _cv_route_executor("stocks.fundamental.cash"),
    "stocks.fundamental.ratios": _cv_route_executor("stocks.fundamental.ratios"),
    "stocks.estimates": _cv_route_executor("stocks.estimates"),
    "stocks.insider_trading": _cv_route_executor("stocks.insider_trading"),
    "government.trades": _cv_route_executor("government.trades"),
    "stocks.filings": _cv_route_executor("stocks.filings"),
    "derivatives.options.screener": _options_screener_executor,
    "derivatives.options.query": _options_query_executor,
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
        _print_json(_tag_intraday_last_bar(symbol, _apply_limit(results, limit)))
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


# Params that are real screening predicates. ``market`` only scopes the search;
# ``limit`` and ``fields`` only shape output. When no predicate is provided, the
# command returns structured help instead of dumping a broad default result set.
_SCREENER_REQUIRED_FILTER_PARAMS = (
    # Keep in sync with equity_screener() predicate parameters.
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
)

_SCREENER_HELP: dict[str, Any] = {
    "usage": "openbb-agent-cli equity.screener [OPTIONS]",
    "description": "股票筛选，支持简单过滤与高级 StockField 过滤。未提供真实过滤条件时返回本帮助，不返回数据。market/limit/fields 只控制范围或输出，不能单独触发查询。",
    "simple_filters": [
        {"param": "--market", "choices": ["america", "hongkong", "china", "global"], "desc": "市场区域（仅限定范围，不能单独触发查询）"},
        {"param": "--limit", "desc": "返回数量，默认 150（仅控制输出，不能单独触发查询）"},
        {"param": "--price-min/--price-max", "desc": "价格区间"},
        {"param": "--volume-min/--volume-max", "desc": "成交量区间"},
        {"param": "--market-cap-min/--market-cap-max", "desc": "市值区间"},
        {"param": "--change-percent-min/--change-percent-max", "desc": "涨跌幅区间 (%)"},
        {"param": "--rsi-min/--rsi-max", "desc": "RSI(14) 区间 (0-100)"},
        {"param": "--sector", "desc": "行业筛选，可多次指定"},
    ],
    "advanced": {
        "filters": "JSON 字符串，任意 StockField 过滤，如 {\"PE_RATIO_TTM\":{\"min\":10,\"max\":25},\"SECTOR\":{\"in\":[\"Technology\"]}}",
        "fields": "JSON 数组字符串，指定返回字段，如 [\"SYMBOL\",\"NAME\",\"PRICE\"]",
    },
    "field_discovery": "字段名未知时先运行: openbb-agent-cli equity.screener.fields --search <关键词>; 需穷举全部字段用 --all",
    "examples": [
        "equity.screener --market america --change-percent-min 5",
        "equity.screener --filters '{\"PE_RATIO_TTM\":{\"max\":20}}'",
        "equity.screener --market america --change-percent-min 5 --fields '[\"SYMBOL\",\"NAME\",\"PRICE\"]'",
    ],
}

# Curated search-hint directory for StockField discovery. Topics are suggestions
# (not a complete taxonomy): ~83% of fields match at least one hint. Overlap is
# intentional. The remaining fields are described in ``unclassified`` below;
# use ``--all`` for exhaustive coverage. Hints are keyword substrings matched
# against StockField name and label by ``equity.screener.fields --search``.
_FIELDS_HELP: dict[str, Any] = {
    "usage": "openbb-agent-cli equity.screener.fields [OPTIONS]",
    "description": "发现 equity.screener 可用的 StockField 过滤字段名。三种互斥模式：无参=帮助，--search=模糊匹配，--all=全量。",
    "modes": {
        "no_args": "返回本帮助（含搜索提示目录与未归类字段说明）",
        "search": "--search <关键词>  模糊匹配字段 name 与 label（子串匹配，可能有少量噪音，建议加字段类型词缩小范围）",
        "all": "--all  返回全部字段（约 3500+，唯一保证完整覆盖的入口）",
    },
    "output_format": [{"name": "字段枚举名", "label": "字段显示名"}],
    "search_hints": [
        {"topic": "价格", "search": "price"},
        {"topic": "涨跌幅", "search": "change"},
        {"topic": "成交量", "search": "volume"},
        {"topic": "市值", "search": "market cap"},
        {"topic": "企业价值", "search": "enterprise value"},
        {"topic": "52周/历史高低", "search": "high"},
        {"topic": "52周/历史高低", "search": "low"},
        {"topic": "开盘/收盘", "search": "open"},
        {"topic": "开盘/收盘", "search": "close"},
        {"topic": "盘前盘后", "search": "premarket"},
        {"topic": "盘前盘后", "search": "postmarket"},
        {"topic": "盘前盘后", "search": "post-market"},
        {"topic": "缺口", "search": "gap"},
        {"topic": "均线 SMA", "search": "SMA"},
        {"topic": "均线 EMA", "search": "EMA"},
        {"topic": "Hull MA", "search": "Hull"},
        {"topic": "均线评级", "search": "Moving Average"},
        {"topic": "RSI", "search": "RSI"},
        {"topic": "MACD", "search": "MACD"},
        {"topic": "布林带", "search": "Bollinger"},
        {"topic": "随机指标", "search": "Stochastic"},
        {"topic": "CCI", "search": "CCI"},
        {"topic": "ATR", "search": "ATR"},
        {"topic": "ADX/DMI", "search": "ADX"},
        {"topic": "方向指标 DMI", "search": "Directional"},
        {"topic": "Aroon", "search": "Aroon"},
        {"topic": "Ichimoku", "search": "Ichimoku"},
        {"topic": "Pivot 支撑阻力", "search": "Pivot"},
        {"topic": "蜡烛形态", "search": "Candle"},
        {"topic": "图形 Pattern", "search": "Pattern"},
        {"topic": "看涨", "search": "Bullish"},
        {"topic": "看跌", "search": "Bearish"},
        {"topic": "多空力量", "search": "Bull Bear"},
        {"topic": "震荡指标", "search": "Oscillator"},
        {"topic": "动量/MOM", "search": "MOM"},
        {"topic": "ROC", "search": "ROC"},
        {"topic": "Williams", "search": "Williams"},
        {"topic": "Chaikin", "search": "Chaikin"},
        {"topic": "资金流", "search": "Money Flow"},
        {"topic": "波动率", "search": "Volatility"},
        {"topic": "Donchian 通道", "search": "Donchian"},
        {"topic": "Keltner 通道", "search": "Keltner"},
        {"topic": "Parabolic SAR", "search": "Parabolic"},
        {"topic": "技术评级", "search": "Technical Rating"},
        {"topic": "Beta 风险", "search": "Beta"},
        {"topic": "负债/债务", "search": "Debt"},
        {"topic": "资产", "search": "Assets"},
        {"topic": "权益 Equity", "search": "Equity"},
        {"topic": "流动比率", "search": "Current Ratio"},
        {"topic": "利息保障", "search": "Interest Coverage"},
        {"topic": "估值比率", "search": "Ratio"},
        {"topic": "收益率 Yield", "search": "Yield"},
        {"topic": "股息", "search": "Dividend"},
        {"topic": "DPS 每股股息", "search": "DPS"},
        {"topic": "EPS", "search": "EPS"},
        {"topic": "营收", "search": "Revenue"},
        {"topic": "利润率", "search": "Margin"},
        {"topic": "盈利能力/ROE/ROA", "search": "Return"},
        {"topic": "EBITDA", "search": "EBITDA"},
        {"topic": "EBIT", "search": "EBIT"},
        {"topic": "现金流", "search": "Cash"},
        {"topic": "成长率", "search": "Growth"},
        {"topic": "毛利", "search": "Gross"},
        {"topic": "净利润", "search": "Net Income"},
        {"topic": "营业收入", "search": "Operating Income"},
        {"topic": "研发", "search": "Research"},
        {"topic": "资本支出", "search": "Capital Expend"},
        {"topic": "周转率", "search": "Turnover"},
        {"topic": "Z-Score/F-Score 评分", "search": "Score"},
        {"topic": "Graham", "search": "Graham"},
        {"topic": "每股", "search": "per Share"},
        {"topic": "分析师评级", "search": "Recommend"},
        {"topic": "目标价", "search": "Target"},
        {"topic": "做空", "search": "Short"},
        {"topic": "流通股/股数", "search": "Shares"},
        {"topic": "板块", "search": "Sector"},
        {"topic": "行业", "search": "Industry"},
        {"topic": "交易所", "search": "Exchange"},
        {"topic": "货币", "search": "Currency"},
        {"topic": "国家", "search": "Country"},
        {"topic": "标识符 ISIN/CUSIP", "search": "ISIN"},
        {"topic": "标识符 ISIN/CUSIP", "search": "CUSIP"},
        {"topic": "元数据 名称/描述/类型", "search": "Name"},
        {"topic": "元数据", "search": "Description"},
        {"topic": "元数据", "search": "Type"},
        {"topic": "财政周期", "search": "Fiscal"},
        {"topic": "财报日期", "search": "Earnings Release"},
        {"topic": "财报日期", "search": "Earnings Date"},
        {"topic": "员工/股东数", "search": "Number of"},
        {"topic": "指数成分", "search": "Index"},
        {"topic": "表现 performance", "search": "Performance"},
        {"topic": "商誉", "search": "Goodwill"},
        {"topic": "回购", "search": "Buyback"},
        {"topic": "利率", "search": "Rate"},
    ],
    "unclassified": {
        "note": "以下类型字段未纳入上方搜索提示目录，因归不进常用财务/技术分析类；可用 --all 浏览或自行尝试 --search 关键词。",
        "categories": [
            {
                "category": "平台内部/技术元数据",
                "reason": "TradingView 平台绘图/数据更新机制字段，与金融分析无关",
                "examples": ["Logoid", "Update-time", "Minmov", "Bars Count", "Provider-id"],
            },
            {
                "category": "ETF/基金结构属性",
                "reason": "ETF/基金特有元数据，非个股筛选维度",
                "examples": ["Aum", "Nav", "Issuer", "Weighting Scheme", "Ucits Compliant Flag"],
            },
            {
                "category": "IPO/债券/衍生品属性",
                "reason": "证券发行/债券/杠杆产品属性",
                "examples": ["IPO Offer Date", "Maturity Date", "Coupon", "Leveraged Flag", "Inverse Flag"],
            },
            {
                "category": "缩写/内部代码财务项",
                "reason": "TV 内部缩写命名的财务科目，含义需查 TV 文档，难以稳定归类",
                "examples": ["Rtc", "Oper Income Fh", "DPS Common Stock Prim Issue"],
            },
        ],
    },
}


def _has_screener_required_filters(**params: Any) -> bool:
    """True when a real screener predicate was explicitly provided."""
    for name in _SCREENER_REQUIRED_FILTER_PARAMS:
        value = params.get(name)
        if value is None:
            continue
        if isinstance(value, str):
            if not value.strip():
                continue
        elif isinstance(value, list):
            if not value or all(not str(item).strip() for item in value):
                continue
        return True
    return False


def _stock_fields_payload(search: str | None = None) -> list[dict[str, str]]:
    """Return StockField name/label payloads, optionally filtered by search."""
    # Local import keeps tvscreener (an openbb-finance transitive dependency)
    # out of CLI startup; only this discovery command pays for it.
    from tvscreener import StockField

    fields = StockField.search(search) if search is not None else StockField
    return [{"name": field.name, "label": field.label} for field in fields]


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
    """Screen equities with simple or advanced StockField filters.

    market/limit/fields 不能单独触发查询，必须提供价格、成交量、行业、filters
    等真实过滤条件。字段名未知时先运行 equity.screener.fields --search <关键词>。
    """
    if not _has_screener_required_filters(
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
        sector=sector,
        filters=filters,
    ):
        _print_json(_SCREENER_HELP)
        return
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


@app.command(name="equity.screener.fields")
def equity_screener_fields(
    search: str | None = None,
    all_: bool = False,
) -> None:
    """发现 equity.screener 可用的 StockField 过滤字段名。

    无参返回结构化帮助（含搜索提示目录与未归类字段说明）。--search 关键词
    模糊匹配字段 name/label。--all 返回全部字段（约 3500+）。两者互斥。
    详细说明请无参运行查看。
    """
    if search is not None and all_:
        _print_json({"error": "--search and --all are mutually exclusive", "code": "CLI_ERROR"})
        raise SystemExit(1)
    if search is not None:
        keyword = search.strip()
        if not keyword:
            _print_json({"error": "--search keyword must not be empty", "code": "CLI_ERROR"})
            raise SystemExit(1)
        try:
            _print_json(_stock_fields_payload(keyword))
        except Exception as exc:
            _print_json({"error": str(exc), "code": _error_code(exc)})
            raise SystemExit(1) from exc
        return
    if all_:
        try:
            _print_json(_stock_fields_payload())
        except Exception as exc:
            _print_json({"error": str(exc), "code": _error_code(exc)})
            raise SystemExit(1) from exc
        return
    _print_json(_FIELDS_HELP)


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
        _print_json(_tag_intraday_last_bar(symbol, _apply_limit(results, limit)))
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
        _print_json(_tag_intraday_last_bar(symbol, _apply_limit(results, limit)))
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


@app.command(name="technical.indicators")
def technical_indicators(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    interval: str = "1d",
    adjusted: bool = False,
    indicators: list[TechnicalIndicator] | None = None,
    rsi_length: int | None = None,
    macd_fast: int | None = None,
    macd_slow: int | None = None,
    macd_signal: int | None = None,
    sma_lengths: list[int] | None = None,
    ema_lengths: list[int] | None = None,
    bbands_length: int | None = None,
    bbands_std: float | None = None,
    atr_length: int | None = None,
    stoch_k: int | None = None,
    stoch_d: int | None = None,
    limit: int | None = None,
) -> None:
    """Compute technical indicators from routed historical prices."""
    try:
        results = _execute_provider_model(
            "TechnicalIndicators",
            {},
            _technical_indicators_params(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                interval=interval,
                adjusted=adjusted,
                indicators=indicators,
                rsi_length=rsi_length,
                macd_fast=macd_fast,
                macd_slow=macd_slow,
                macd_signal=macd_signal,
                sma_lengths=sma_lengths,
                ema_lengths=ema_lengths,
                bbands_length=bbands_length,
                bbands_std=bbands_std,
                atr_length=atr_length,
                stoch_k=stoch_k,
                stoch_d=stoch_d,
            ),
        )
        _print_json(_apply_limit(results, limit))
    except Exception as exc:
        _print_json({"error": str(exc), "code": _error_code(exc)})
        raise SystemExit(1) from exc


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


from openbb_finance.models.equity_options_chain import FinanceOptionsChainFetcher


@app.command(name="derivatives.options.chain")
def derivatives_options_chain(
    symbol: str,
    expiration: str | None = None,
    option_type: Literal["call", "put"] | None = None,
    min_dte: int | None = None,
    max_dte: int | None = None,
    sort_by: Literal["expiration", "strike", "open_interest", "volume", "implied_volatility", "delta", "bid", "ask", "vwap"] = "open_interest",
    sort_dir: Literal["asc", "desc"] = "desc",
    limit: int = 50,
) -> None:
    """Get option contracts for a symbol with filtering and sorting (ConvexValue /chains).

    Returns {results, _meta} where _meta.total is the server-reported contract
    count and _meta.filtered is the count after local filtering. Without filters
    this can be large (SPY ~13k contracts); use --expiration/--option-type/--limit
    to scope. limit=0 returns all filtered records.
    """
    import asyncio
    try:
        async def _fetch() -> tuple[list[dict[str, Any]], int]:
            q = FinanceOptionsChainFetcher.transform_query({"symbol": symbol})
            data = await FinanceOptionsChainFetcher.aextract_data(q, None)
            records = data.get("records", [])
            total = data.get("contract_count", len(records))
            return records, total

        records, total = asyncio.run(_fetch())
        # Local filters (expiration/option_type handled here because records
        # use date objects, not the string values the CLI receives).
        if expiration:
            from datetime import date as _date
            exp_date = _date.fromisoformat(expiration)
            records = [r for r in records if r.get("expiration") == exp_date]
        if option_type:
            records = [r for r in records if r.get("option_type") == option_type]
        if min_dte is not None:
            records = [r for r in records if r.get("dte") is not None and r["dte"] >= min_dte]
        if max_dte is not None:
            records = [r for r in records if r.get("dte") is not None and r["dte"] <= max_dte]
        filtered, meta = _filter_sort_limit(
            records, sort_by=sort_by, sort_dir=sort_dir,
            limit=limit if limit > 0 else None,
        )
        _print_results_with_meta(filtered, meta, total=total)
    except Exception as exc:
        _print_json({"error": str(exc), "code": _error_code(exc)})
        raise SystemExit(1) from exc


@app.command(name="derivatives.options.historical")
def derivatives_options_historical(
    symbol: str,
    multiplier: int = 1,
    timespan: str = "day",
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    """Get aggregated OHLCV bars for an option contract (ConvexValue /mas/aggs).

    symbol is the OCC-style option ticker, e.g. O:SPY260731C00750000.
    """
    _run_cv_route(
        "derivatives.options.historical",
        symbol=symbol,
        multiplier=multiplier,
        timespan=timespan,
        start_date=start_date,
        end_date=end_date,
    )


@app.command(name="derivatives.options.daily")
def derivatives_options_daily(
    symbol: str,
    date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    """Get single-day OHLCV for an option contract (ConvexValue /mas/open-close)."""
    _run_cv_route(
        "derivatives.options.daily",
        symbol=symbol,
        date=date,
        start_date=start_date,
        end_date=end_date,
    )


@app.command(name="derivatives.options.screener")
def derivatives_options_screener(
    underlying_symbol: str | None = None,
    option_type: Literal["call", "put"] | None = None,
    min_open_interest: float | None = None,
    max_open_interest: float | None = None,
    min_volume: float | None = None,
    min_iv: float | None = None,
    max_iv: float | None = None,
    delta_min: float | None = None,
    delta_max: float | None = None,
    expiration_date: str | None = None,
    sort_by: str = "open_interest",
    sort_dir: Literal["asc", "desc"] = "desc",
    limit: int = 50,
    extra_filters: str | None = None,
) -> None:
    """Screen option contracts across symbols (ConvexValue /screen).

    extra_filters is a JSON string of CV-native filter objects, e.g.
    '[{"field":"day_volume","op":"gt_field","value":"open_interest"}]'.
    """
    # Custom provider model: all params belong in extra_params (standard is
    # empty for fetcher_dict-registered models without an OpenBB standard
    # QueryParams counterpart). Mirrors the technical.indicators pattern.
    # Keep None values so they override the Query() defaults the dynamic
    # OptionsScreener class injects; dropping them lets Query leak through.
    import json as _json
    import asyncio
    from openbb_finance.sources import convexvalue as _cv
    from openbb_finance.models.equity_options_screener import (
        FinanceOptionsScreenerQueryParams, _build_filters, DEFAULT_COLUMNS as _SCR_COLS,
    )
    try:
        q = FinanceOptionsScreenerQueryParams(
            underlying_symbol=underlying_symbol, option_type=option_type,
            min_open_interest=min_open_interest, max_open_interest=max_open_interest,
            min_volume=min_volume, min_iv=min_iv, max_iv=max_iv,
            delta_min=delta_min, delta_max=delta_max,
            expiration_date=expiration_date, sort_by=sort_by, sort_dir=sort_dir,
            limit=limit, extra_filters=_json.loads(extra_filters) if extra_filters else None,
        )
        filters = _build_filters(q)
        sort_list = [{"field": q.sort_by, "direction": q.sort_dir}] if q.sort_by else None
        raw = asyncio.run(_cv.fetch_screen(
            columns=list(_SCR_COLS), filters=filters, sort=sort_list, limit=q.limit,
        ))
        columns = raw.get("columns", [])
        rows = raw.get("rows", [])
        records = [dict(zip(columns, row, strict=False)) for row in rows]
        meta = {
            "returned": len(records),
            "row_count": raw.get("row_count", len(records)),
            "truncated": raw.get("truncated", False),
            "sort_by": sort_by, "sort_dir": sort_dir,
        }
        _print_results_with_meta(records, meta)
    except Exception as exc:
        _print_json({"error": str(exc), "code": _error_code(exc)})
        raise SystemExit(1) from exc


@app.command(name="derivatives.options.query")
def derivatives_options_query(sql: str, max_rows: int = 5000) -> None:
    """Run a read-only SELECT/WITH SQL against the options_snapshots table (ConvexValue /query).

    DDL/DML are rejected server-side. See the openbb-agent-cli skill for SQL
    templates (GEX ranking, term structure, market PCR, max pain, etc.).
    Returns {results, _meta} where _meta.row_count/truncated come from the server.
    """
    import asyncio
    from openbb_finance.sources import convexvalue as _cv
    try:
        raw = asyncio.run(_cv.fetch_query(sql, max_rows=max_rows))
        rows = raw.get("rows", [])
        meta = {
            "returned": len(rows),
            "row_count": raw.get("row_count", len(rows)),
            "truncated": raw.get("truncated", False),
            "elapsed_ms": raw.get("elapsed_ms"),
        }
        _print_results_with_meta(rows, meta)
    except Exception as exc:
        _print_json({"error": str(exc), "code": _error_code(exc)})
        raise SystemExit(1) from exc


@app.command(name="stocks.fundamental.income")
def stocks_fundamental_income(
    symbol: str,
    period: Literal["annual", "quarter", "ttm"] = "annual",
    limit: int = 5,
) -> None:
    """Get income statements (ConvexValue/FMP). Sorted by period_ending desc."""
    _run_cv_list("IncomeStatement", extra_params={"symbol": symbol, "period": period, "limit": limit},
                 sort_by="period_ending", sort_dir="desc")


@app.command(name="stocks.fundamental.balance")
def stocks_fundamental_balance(
    symbol: str,
    period: Literal["annual", "quarter", "ttm"] = "annual",
    limit: int = 5,
) -> None:
    """Get balance sheet statements (ConvexValue/FMP). Sorted by period_ending desc."""
    _run_cv_list("BalanceSheetStatement", extra_params={"symbol": symbol, "period": period, "limit": limit},
                 sort_by="period_ending", sort_dir="desc")


@app.command(name="stocks.fundamental.cash")
def stocks_fundamental_cash(
    symbol: str,
    period: Literal["annual", "quarter", "ttm"] = "annual",
    limit: int = 5,
) -> None:
    """Get cash flow statements (ConvexValue/FMP). Sorted by period_ending desc."""
    _run_cv_list("CashFlowStatement", extra_params={"symbol": symbol, "period": period, "limit": limit},
                 sort_by="period_ending", sort_dir="desc")


@app.command(name="stocks.fundamental.ratios")
def stocks_fundamental_ratios(
    symbol: str,
    period: Literal["annual", "quarter"] = "annual",
    limit: int = 5,
) -> None:
    """Get financial ratios (ConvexValue/FMP). Sorted by period_ending desc."""
    _run_cv_list("FinancialRatios", extra_params={"symbol": symbol, "period": period, "limit": limit},
                 sort_by="period_ending", sort_dir="desc")


@app.command(name="stocks.estimates")
def stocks_estimates(
    symbol: str,
    period: Literal["annual", "quarter"] = "annual",
    limit: int = 10,
) -> None:
    """Get analyst estimates (ConvexValue/FMP). Sorted by date desc."""
    _run_cv_list("AnalystEstimates", extra_params={"symbol": symbol, "period": period, "limit": limit},
                 sort_by="date", sort_dir="desc")


@app.command(name="stocks.insider_trading")
def stocks_insider_trading(
    symbol: str,
    transaction_type: str | None = None,
    after: str | None = None,
    limit: int = 50,
) -> None:
    """Get insider trades (ConvexValue/FMP).

    transaction_type: FMP code, e.g. P-Purchase, S-Sale, M-Exempt (server-side).
    after: YYYY-MM-DD, only trades after this date (server-side).
    Output sorted by filing_date desc.
    """
    _run_cv_list("InsiderTrading",
                 extra_params={"symbol": symbol, "transaction_type": transaction_type,
                               "after": after, "limit": limit},
                 sort_by="filing_date", sort_dir="desc")


@app.command(name="government.trades")
def government_trades(
    symbol: str | None = None,
    page: int | None = None,
    limit: int = 50,
) -> None:
    """Get Senate trading disclosures (ConvexValue/FMP).

    page: 0-indexed page number (server-side pagination).
    Output sorted by transaction_date desc.
    """
    _run_cv_list("GovernmentTrades",
                 extra_params={"symbol": symbol, "page": page, "limit": limit},
                 sort_by="transaction_date", sort_dir="desc")


@app.command(name="etf.holdings")
def etf_holdings(
    symbol: str,
    sort_by: Literal["weight_percentage", "market_value", "shares_number"] = "weight_percentage",
    sort_dir: Literal["asc", "desc"] = "desc",
    limit: int = 20,
) -> None:
    """Get ETF holdings (ConvexValue/FMP).

    Server returns ALL holdings (limit is ignored upstream); this command sorts
    locally then truncates. Default: top 20 by weight.
    """
    # Server ignores limit, so request everything and truncate here.
    _run_cv_list("EtfHoldings",
                 extra_params={"symbol": symbol, "limit": None},
                 sort_by=sort_by, sort_dir=sort_dir, limit=limit)


@app.command(name="etf.sectors")
def etf_sectors(symbol: str) -> None:
    """Get ETF sector weightings (ConvexValue/FMP)."""
    _run_cv_route("etf.sectors", symbol=symbol)


@app.command(name="stocks.filings")
def stocks_filings(
    symbol: str,
    from_date: str | None = None,
    to_date: str | None = None,
    page: int | None = None,
    limit: int = 50,
) -> None:
    """Get SEC 8-K filings (ConvexValue/FMP).

    from_date/to_date (YYYY-MM-DD) and page are server-side filters.
    Output sorted by filing_date desc.
    """
    _run_cv_list("CompanyFilings",
                 extra_params={"symbol": symbol, "from_date": from_date,
                               "to_date": to_date, "page": page, "limit": limit},
                 sort_by="filing_date", sort_dir="desc")


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
