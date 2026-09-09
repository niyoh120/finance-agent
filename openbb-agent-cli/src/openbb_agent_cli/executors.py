"""Route/model executors and shared helpers for the agent CLI.

Everything that turns a route name + params into provider results lives here:
JSON output helpers, market-hours logic, the OpenBB provider-model bridge
(including the FastAPI Query-marker default handling), per-route executors
(``COMMAND_EXECUTORS``) and ConvexValue-specific standard/extra parameter
splitting. Command definitions stay in :mod:`openbb_agent_cli.cli`; batch
query templating lives in :mod:`openbb_agent_cli.batch`.
"""

from __future__ import annotations

import contextlib
import io
import json
from collections.abc import Callable
from dataclasses import is_dataclass
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from cyclopts.exceptions import CycloptsError
from openbb_finance.sources.base import SourceError
from openbb_finance.sources.symbols import infer_market_from_symbol

from .output import build_success_envelope


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
    tagged = [
        {
            **last,
            "_meta": {
                "warning": "market is currently open; this bar may be a partial-session snapshot, OHLCV not final",
                "market": market,
            },
        }
    ]
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
    "futures.price.historical": "FuturesHistorical",
    "futures.price.quote": "FuturesQuote",
    "futures.search": "FuturesSearch",
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

# CLI 命令名 -> OpenBB 模型名（静态 _schema 的描述来源）。route 命令复用
# ROUTE_MODELS；直连 provider 模型的命令在此补全。横线命名的
# economy.available-indicators 对应 ROUTE_MODELS 的下划线路由键。
COMMAND_MODELS: dict[str, str] = {
    **ROUTE_MODELS,
    "economy.available-indicators": ROUTE_MODELS["economy.available_indicators"],
    "index.snapshots": "IndexSnapshots",
    "technical.indicators": "TechnicalIndicators",
    "etf.search": "EtfSearch",
    "derivatives.options.screener": "OptionsScreener",
}

# 结果字段动态、无法静态描述的命令：成功输出省略 _schema。
DYNAMIC_FIELD_COMMANDS = frozenset({"equity.screener", "derivatives.options.query"})

# 自由 SQL 动态列：空字符串是表达式可显式产生的有意义值，清理时保持原样。
MEANINGFUL_EMPTY_STRING_COMMANDS = frozenset({"derivatives.options.query"})


def schema_model_for(command: str) -> str | None:
    """Static schema model for a CLI data command; None omits _schema.

    A command that is neither dynamic nor mapped is an implementation gap
    and fails loudly here (the offline mapping-completeness test catches it
    before release).
    """
    if command in DYNAMIC_FIELD_COMMANDS:
        return None
    try:
        return COMMAND_MODELS[command]
    except KeyError:
        raise ValueError(f"no schema model mapped for command: {command}") from None


def keeps_empty_strings(command: str) -> bool:
    """True when the command's empty strings carry meaning (free-SQL columns)."""
    return command in MEANINGFUL_EMPTY_STRING_COMMANDS


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
        records = _execute_route(route, **params)
        _print_json(build_success_envelope(records, model_name=schema_model_for(route)))
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
        records = _execute_provider_model(ROUTE_MODELS[route], standard, extra)
        _print_json(build_success_envelope(records, model_name=schema_model_for(route)))
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
        # The generated standard/extra dataclasses default unset optional fields
        # to fastapi Query(...) markers; asdict() later feeds those markers to
        # the fetcher's pydantic QueryParams and fails validation. Fill every
        # field explicitly with its real default so no marker leaks through:
        # extract the Query(marker).default value (None for truly optional
        # fields, the declared default e.g. "1d"/False for fields that have one,
        # and None for required fields whose default is PydanticUndefined).
        from dataclasses import MISSING as DATACLASS_MISSING
        from dataclasses import fields as dataclass_fields

        def _query_marker_default(default: Any) -> tuple[bool, Any]:
            """Return (is_fastapi_query_marker, real_default)."""
            if type(default).__name__ == "Query" and hasattr(default, "default"):
                real = default.default
                if type(real).__name__ == "PydanticUndefined":
                    return True, None
                return True, real
            return False, default

        def _field_default(field: Any) -> Any:
            if field.default_factory is not DATACLASS_MISSING:
                try:
                    return field.default_factory()
                except Exception:
                    return None
            is_marker, real = _query_marker_default(field.default)
            if is_marker:
                return real
            if field.default is DATACLASS_MISSING:
                return None
            return field.default

        standard_defaults = {field.name: _field_default(field) for field in dataclass_fields(standard_cls)}
        extra_defaults = {field.name: _field_default(field) for field in dataclass_fields(extra_cls)}
        standard = standard_cls(**{**standard_defaults, **standard_values})
        extra = extra_cls(**{**extra_defaults, **extra_values})
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
        records = _execute_provider_model(model_name, standard_params, extra_params)
        _print_json(build_success_envelope(records, model_name=model_name))
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
    *,
    model_name: str | None = None,
    keep_empty_strings: bool = False,
) -> None:
    """Print ``{results, _schema?, _meta?}`` with the same null cleaning applied
    to both records and meta. ``model_name=None`` omits ``_schema``."""
    if total is not None:
        meta = {**meta, "total": total}
    _print_json(
        build_success_envelope(records, model_name=model_name, meta=meta, keep_empty_strings=keep_empty_strings)
    )


def _run_cv_list(
    model_name: str,
    *,
    standard_params: dict[str, Any] | None = None,
    extra_params: dict[str, Any] | None = None,
    sort_by: str | None = None,
    sort_dir: Literal["asc", "desc"] = "desc",
    limit: int | None = None,
) -> None:
    """Run a ConvexValue list-returning model and wrap output as {results, _meta}.

    Fetches via _execute_provider_model (which returns list[dict]), then applies
    local sort + limit. _meta reports returned/filtered/sort info; FMP endpoints
    do not expose a server total so `total` is omitted (the caller can infer
    "there may be more" from filtered > returned).
    """
    try:
        records = _execute_provider_model(model_name, standard_params, extra_params)
        filtered, meta = _filter_sort_limit(
            records,
            sort_by=sort_by,
            sort_dir=sort_dir,
            limit=limit,
        )
        _print_results_with_meta(filtered, meta, model_name=model_name)
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
    "futures.price.historical": {"interval": "1d", "adjusted": False},
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


def _cv_api_key() -> str:
    """Resolve the ConvexValue API key without raising.

    Same precedence as convexvalue._get_api_key (live env var first, then the
    loaded source config); used only to decide whether the CV side of the
    options-chain aggregation participates.
    """
    import os

    key = os.environ.get("CV_API_KEY", "").strip()
    if not key:
        from openbb_finance.config import get_source_config

        key = (get_source_config("convexvalue").api_key or "").strip()
    return key


def _filter_cv_chain_window(
    records: list[dict[str, Any]],
    *,
    dte: int,
    strike_count: int,
) -> list[dict[str, Any]]:
    """Apply the Schwab-equivalent query window locally to flattened CV records.

    CV /chains has no server-side dte/strike_count filters, so the aggregate
    mode emulates them: keep contracts with dte <= *dte*, then per expiration
    keep the *strike_count* strike levels nearest to the underlying price
    (both call and put rows at a kept strike survive).
    """
    records = [r for r in records if r.get("dte") is not None and r["dte"] <= dte]
    by_expiration: dict[Any, list[dict[str, Any]]] = {}
    for record in records:
        by_expiration.setdefault(record.get("expiration"), []).append(record)
    kept: list[dict[str, Any]] = []
    for rows in by_expiration.values():
        reference = next((r.get("underlying_price") for r in rows if r.get("underlying_price") is not None), None)
        if reference is None:
            kept.extend(rows)
            continue
        strikes = sorted(
            {r["strike"] for r in rows if r.get("strike") is not None},
            key=lambda s: (abs(s - reference), s),
        )
        keep = set(strikes[:strike_count])
        kept.extend(r for r in rows if r.get("strike") in keep)
    return kept


async def _aggregate_options_chain(
    symbol: str,
    *,
    dte: int,
    strike_count: int,
    range_: str | None,
    strategy: str | None,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """Merge the Schwab and ConvexValue chains field-by-field.

    Source order IS the priority (schwab first): in-window contracts take
    every populated field from Schwab (unified pricing/greeks conventions,
    trusted quote timestamps); CV fills fields Schwab leaves null and
    contributes out-of-window contracts (far-dated / deep-OTM) on its own —
    the CV side stays the full chain here so the merged output keeps the
    full-chain skeleton (--source cv is the branch that emulates the Schwab
    window locally). Any single source failure is swallowed by
    aggregate_records and degrades to the other source alone. The
    aggregator's {field}_source annotations are stripped so the output shape
    matches the previous single-source output exactly; only
    _meta.sources_used reveals which sources participated.
    """
    from types import SimpleNamespace

    from openbb_finance.aggregator import aggregate_records
    from openbb_finance.models.equity_options_chain import FinanceOptionsChainFetcher
    from openbb_finance.registry import build_default_registry

    schwab = build_default_registry().get("schwab")
    cv_source = SimpleNamespace(name="convexvalue", enabled=bool(_cv_api_key()))
    state: dict[str, Any] = {"cv_total": None, "sources_used": []}

    async def fetch(source: Any) -> list[dict[str, Any]]:
        if source.name == "schwab":
            data = await source.fetch_options_chain(
                symbol, dte=dte, strike_count=strike_count, range_=range_, strategy=strategy
            )
            state["sources_used"].append("schwab")
            # Schwab's server-side daysToExpiration filter is loose (contracts
            # beyond the declared window still come back), so enforce the
            # user-declared window locally; strike_count is honored server-side.
            return [r for r in data["records"] if r.get("dte") is not None and r["dte"] <= dte]
        query = FinanceOptionsChainFetcher.transform_query({"symbol": symbol})
        data = await FinanceOptionsChainFetcher.aextract_data(query, None)
        state["cv_total"] = data.get("contract_count", 0)
        state["sources_used"].append("convexvalue")
        # Full chain on purpose: out-of-window contracts (far-dated /
        # deep-OTM) survive here and come out as all-CV rows.
        return data.get("records", [])

    participants = [s for s in (schwab, cv_source) if s is not None and s.enabled]
    merged = await aggregate_records(participants, fetch, key_fields=("expiration", "strike", "option_type"))
    records = [{k: v for k, v in row.items() if not k.endswith("_source")} for row in merged]
    # CV's server-reported total is the closest thing to a contract count for
    # the union; when CV failed, the merged row count is the honest number.
    total = state["cv_total"] if state["cv_total"] is not None else len(records)
    return records, total, state["sources_used"]


def _options_chain_execute(params: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Shared core for the derivatives.options.chain CLI command and batch executor.

    Params: symbol, dte, strike_count (both mandatory — the declared query
    window), optional source ('cv'|'schwab' forces a single source),
    expiration/option_type/min_dte local filters, range_/strategy (Schwab
    only), sort_by/sort_dir/limit.

    Returns (records, meta): meta carries returned/filtered plus `total`
    (contract count) and `sources_used` (aggregate mode only).
    """
    import asyncio
    from datetime import date as _date

    symbol = params.get("symbol")
    if not symbol:
        raise ValueError("symbol is required")
    dte = params.get("dte")
    strike_count = params.get("strike_count")
    if dte is None or strike_count is None:
        raise ValueError("options.chain requires dte and strike_count (declare the query window)")
    dte = int(dte)
    strike_count = int(strike_count)
    range_ = params.get("range_") or params.get("range")
    strategy = params.get("strategy")

    async def _fetch() -> tuple[list[dict[str, Any]], int, list[str] | None]:
        source_choice = params.get("source")
        if source_choice == "schwab":
            from openbb_finance.registry import build_default_registry

            schwab = build_default_registry().get("schwab")
            if schwab is None or not schwab.enabled:
                raise SourceError("schwab source is disabled; set SCHWAB_API_BASE_URL (and optional SCHWAB_API_KEY)")
            data = await schwab.fetch_options_chain(
                str(symbol), dte=dte, strike_count=strike_count, range_=range_, strategy=strategy
            )
            # Same local window enforcement as aggregate mode: Schwab's
            # server-side dte filter is loose.
            records = [r for r in data["records"] if r.get("dte") is not None and r["dte"] <= dte]
            return records, data["contract_count"], ["schwab"]
        if source_choice == "cv":
            from openbb_finance.models.equity_options_chain import FinanceOptionsChainFetcher

            query = FinanceOptionsChainFetcher.transform_query({"symbol": symbol})
            data = await FinanceOptionsChainFetcher.aextract_data(query, None)
            records = _filter_cv_chain_window(data.get("records", []), dte=dte, strike_count=strike_count)
            return records, data.get("contract_count", len(records)), ["convexvalue"]
        return await _aggregate_options_chain(
            str(symbol), dte=dte, strike_count=strike_count, range_=range_, strategy=strategy
        )

    records, total, sources_used = asyncio.run(_fetch())
    if params.get("expiration"):
        exp_date = _date.fromisoformat(str(params["expiration"]))
        records = [r for r in records if r.get("expiration") == exp_date]
    if params.get("option_type"):
        records = [r for r in records if r.get("option_type") == params["option_type"]]
    min_dte = params.get("min_dte")
    if min_dte is not None:
        records = [r for r in records if r.get("dte") is not None and r["dte"] >= min_dte]
    records, meta = _filter_sort_limit(
        records,
        sort_by=params.get("sort_by", "open_interest"),
        sort_dir=params.get("sort_dir", "desc"),
        limit=params.get("limit") if isinstance(params.get("limit"), int) and params.get("limit", 0) > 0 else None,
    )
    meta["total"] = total
    if sources_used is not None:
        meta["sources_used"] = sources_used
    return records, meta


def _options_chain_batch_executor(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Batch executor for options chain: aggregate/fetch via sources, apply limit."""
    # Safety default for batch callers that omit limit (aggregated output can
    # span the full CV chain skeleton).
    if params.get("limit") is None:
        params = {"limit": 100, **params}
    records, _meta = _options_chain_execute(params)
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
    "futures.price.historical": _historical_executor("futures.price.historical"),
    "futures.price.quote": _route_executor("futures.price.quote"),
    "futures.search": _route_executor("futures.search"),
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
