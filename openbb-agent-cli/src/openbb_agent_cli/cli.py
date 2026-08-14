"""Agent-friendly JSON CLI for the OpenBB finance provider.

Command definitions (cyclopts ``@app.command``) live here; the route/model
executor machinery is in :mod:`openbb_agent_cli.executors` and batch query
templating in :mod:`openbb_agent_cli.batch`. The executor names are re-exported
below so command call sites and tests can keep resolving them on this module.
"""

from __future__ import annotations

from typing import Any, Literal

from cyclopts import App
from cyclopts.exceptions import CycloptsError
from openbb_finance.models.equity_options_chain import FinanceOptionsChainFetcher

from openbb_agent_cli import __version__

# 以下 re-export 供测试与旧调用方在 cli 模块上继续解析；命令本体不直接使用。
from openbb_agent_cli.batch import (  # noqa: E402, F401
    _build_template_queries,
    _execute_batch_query,
    _parse_batch_queries,
    _run_batch_queries,
)
from openbb_agent_cli.executors import (  # noqa: E402, F401
    COMMAND_EXECUTORS,
    ROUTE_MODELS,
    TechnicalIndicator,
    _apply_limit,
    _drop_none,
    _ensure_list,
    _error_code,
    _execute_provider_model,
    _execute_route,
    _filter_sort_limit,
    _historical_executor,
    _is_market_open,
    _print_json,
    _print_results_with_meta,
    _run_cv_list,
    _run_cv_route,
    _run_provider_model,
    _run_route,
    _tag_intraday_last_bar,
    _technical_indicators_params,
    infer_market_from_symbol,
)

app = App(name="openbb-agent-cli", version=__version__, help="Agent-friendly JSON CLI for openbb-finance.")


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
    "description": (
        "股票筛选，支持简单过滤与高级 StockField 过滤。未提供真实过滤条件时返回本帮助，不返回数据。"
        "market/limit/fields 只控制范围或输出，不能单独触发查询。"
    ),
    "simple_filters": [
        {
            "param": "--market",
            "choices": ["america", "hongkong", "china", "global"],
            "desc": "市场区域（仅限定范围，不能单独触发查询）",
        },
        {"param": "--limit", "desc": "返回数量，默认 150（仅控制输出，不能单独触发查询）"},
        {"param": "--price-min/--price-max", "desc": "价格区间"},
        {"param": "--volume-min/--volume-max", "desc": "成交量区间"},
        {"param": "--market-cap-min/--market-cap-max", "desc": "市值区间"},
        {"param": "--change-percent-min/--change-percent-max", "desc": "涨跌幅区间 (%)"},
        {"param": "--rsi-min/--rsi-max", "desc": "RSI(14) 区间 (0-100)"},
        {"param": "--sector", "desc": "行业筛选，可多次指定"},
    ],
    "advanced": {
        "filters": (
            'JSON 字符串，任意 StockField 过滤，如 {"PE_RATIO_TTM":{"min":10,"max":25},"SECTOR":{"in":["Technology"]}}'
        ),
        "fields": 'JSON 数组字符串，指定返回字段，如 ["SYMBOL","NAME","PRICE"]',
    },
    "field_discovery": (
        "字段名未知时先运行: openbb-agent-cli equity.screener.fields --search <关键词>; 需穷举全部字段用 --all"
    ),
    "examples": [
        "equity.screener --market america --change-percent-min 5",
        'equity.screener --filters \'{"PE_RATIO_TTM":{"max":20}}\'',
        'equity.screener --market america --change-percent-min 5 --fields \'["SYMBOL","NAME","PRICE"]\'',
    ],
}

# Curated search-hint directory for StockField discovery. Topics are suggestions
# (not a complete taxonomy): ~83% of fields match at least one hint. Overlap is
# intentional. The remaining fields are described in ``unclassified`` below;
# use ``--all`` for exhaustive coverage. Hints are keyword substrings matched
# against StockField name and label by ``equity.screener.fields --search``.
_FIELDS_HELP: dict[str, Any] = {
    "usage": "openbb-agent-cli equity.screener.fields [OPTIONS]",
    "description": (
        "发现 equity.screener 可用的 StockField 过滤字段名。三种互斥模式：无参=帮助，--search=模糊匹配，--all=全量。"
    ),
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
        "note": (
            "以下类型字段未纳入上方搜索提示目录，因归不进常用财务/技术分析类；"
            "可用 --all 浏览或自行尝试 --search 关键词。"
        ),
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


@app.command(name="futures.price.historical")
def futures_price_historical(
    symbol: str,
    expiration: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    interval: str = "1d",
    adjusted: bool = False,
    limit: int | None = None,
) -> None:
    """Get futures historical price data.

    symbol: variety code + exchange short code, e.g. rb.SHFE, IF.CFFEX,
        GC.COMEX, AU.SGE. No --expiration means the main continuous contract;
        pass --expiration YYYY-MM for a specific month contract.
    """
    try:
        results = _execute_route(
            "futures.price.historical",
            symbol=symbol,
            expiration=expiration,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
            adjusted=adjusted,
        )
        _print_json(_apply_limit(results, limit))
    except Exception as exc:
        _print_json({"error": str(exc), "code": _error_code(exc)})
        raise SystemExit(1) from exc


@app.command(name="futures.price.quote")
def futures_price_quote(symbol: str, expiration: str | None = None) -> None:
    """Get a futures quote.

    symbol: variety code + exchange short code, e.g. rb.SHFE, GC.COMEX,
        AU.SGE. No --expiration means the main continuous contract.
    """
    _run_route("futures.price.quote", symbol=symbol, expiration=expiration)


@app.command(name="futures.search")
def futures_search(query: str, is_symbol: bool = False) -> None:
    """Search futures contracts by variety code, user symbol, or Chinese name.

    query: e.g. si / si.GFEX (symbol, pass --is-symbol) or 工业硅 / 沪深300
        (Chinese product name).
    """
    _run_route("futures.search", query=query, is_symbol=is_symbol)


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


@app.command(name="derivatives.options.chain")
def derivatives_options_chain(
    symbol: str,
    expiration: str | None = None,
    option_type: Literal["call", "put"] | None = None,
    min_dte: int | None = None,
    max_dte: int | None = None,
    sort_by: Literal[
        "expiration", "strike", "open_interest", "volume", "implied_volatility", "delta", "bid", "ask", "vwap"
    ] = "open_interest",
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
            records,
            sort_by=sort_by,
            sort_dir=sort_dir,
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
    import asyncio
    import json as _json

    from openbb_finance.models.equity_options_screener import (
        DEFAULT_COLUMNS as _SCR_COLS,
    )
    from openbb_finance.models.equity_options_screener import (
        FinanceOptionsScreenerQueryParams,
        _build_filters,
    )
    from openbb_finance.sources import convexvalue as _cv

    try:
        q = FinanceOptionsScreenerQueryParams(
            underlying_symbol=underlying_symbol,
            option_type=option_type,
            min_open_interest=min_open_interest,
            max_open_interest=max_open_interest,
            min_volume=min_volume,
            min_iv=min_iv,
            max_iv=max_iv,
            delta_min=delta_min,
            delta_max=delta_max,
            expiration_date=expiration_date,
            sort_by=sort_by,
            sort_dir=sort_dir,
            limit=limit,
            extra_filters=_json.loads(extra_filters) if extra_filters else None,
        )
        filters = _build_filters(q)
        sort_list = [{"field": q.sort_by, "direction": q.sort_dir}] if q.sort_by else None
        raw = asyncio.run(
            _cv.fetch_screen(
                columns=list(_SCR_COLS),
                filters=filters,
                sort=sort_list,
                limit=q.limit,
            )
        )
        columns = raw.get("columns", [])
        rows = raw.get("rows", [])
        records = [dict(zip(columns, row, strict=False)) for row in rows]
        meta = {
            "returned": len(records),
            "row_count": raw.get("row_count", len(records)),
            "truncated": raw.get("truncated", False),
            "sort_by": sort_by,
            "sort_dir": sort_dir,
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
    _run_cv_list(
        "IncomeStatement",
        extra_params={"symbol": symbol, "period": period, "limit": limit},
        sort_by="period_ending",
        sort_dir="desc",
    )


@app.command(name="stocks.fundamental.balance")
def stocks_fundamental_balance(
    symbol: str,
    period: Literal["annual", "quarter", "ttm"] = "annual",
    limit: int = 5,
) -> None:
    """Get balance sheet statements (ConvexValue/FMP). Sorted by period_ending desc."""
    _run_cv_list(
        "BalanceSheetStatement",
        extra_params={"symbol": symbol, "period": period, "limit": limit},
        sort_by="period_ending",
        sort_dir="desc",
    )


@app.command(name="stocks.fundamental.cash")
def stocks_fundamental_cash(
    symbol: str,
    period: Literal["annual", "quarter", "ttm"] = "annual",
    limit: int = 5,
) -> None:
    """Get cash flow statements (ConvexValue/FMP). Sorted by period_ending desc."""
    _run_cv_list(
        "CashFlowStatement",
        extra_params={"symbol": symbol, "period": period, "limit": limit},
        sort_by="period_ending",
        sort_dir="desc",
    )


@app.command(name="stocks.fundamental.ratios")
def stocks_fundamental_ratios(
    symbol: str,
    period: Literal["annual", "quarter"] = "annual",
    limit: int = 5,
) -> None:
    """Get financial ratios (ConvexValue/FMP). Sorted by period_ending desc."""
    _run_cv_list(
        "FinancialRatios",
        extra_params={"symbol": symbol, "period": period, "limit": limit},
        sort_by="period_ending",
        sort_dir="desc",
    )


@app.command(name="stocks.estimates")
def stocks_estimates(
    symbol: str,
    period: Literal["annual", "quarter"] = "annual",
    limit: int = 10,
) -> None:
    """Get analyst estimates (ConvexValue/FMP). Sorted by date desc."""
    _run_cv_list(
        "AnalystEstimates",
        extra_params={"symbol": symbol, "period": period, "limit": limit},
        sort_by="date",
        sort_dir="desc",
    )


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
    _run_cv_list(
        "InsiderTrading",
        extra_params={"symbol": symbol, "transaction_type": transaction_type, "after": after, "limit": limit},
        sort_by="filing_date",
        sort_dir="desc",
    )


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
    _run_cv_list(
        "GovernmentTrades",
        extra_params={"symbol": symbol, "page": page, "limit": limit},
        sort_by="transaction_date",
        sort_dir="desc",
    )


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
    _run_cv_list(
        "EtfHoldings", extra_params={"symbol": symbol, "limit": None}, sort_by=sort_by, sort_dir=sort_dir, limit=limit
    )


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
    _run_cv_list(
        "CompanyFilings",
        extra_params={"symbol": symbol, "from_date": from_date, "to_date": to_date, "page": page, "limit": limit},
        sort_by="filing_date",
        sort_dir="desc",
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
