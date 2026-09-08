"""Cross-package HTTP contract test: real tdx-api app behind real TdxSource.

The only cross-package import in the repository lives here (tests only): the
real ``create_app``/query layer/response models from services/tdx-api answer
through ``httpx.ASGITransport`` while the upstream TDX sockets are replaced by
command-level fake sessions. This pins the wire contract both sides agree on
(envelope shapes, paging metadata, error envelopes, capability errors) without
any real network.
"""

from datetime import date, datetime

import httpx
import pytest
from openbb_finance.config import SourceConfig
from openbb_finance.models.equity_historical import FinanceEquityHistoricalFetcher
from openbb_finance.sources.base import PriceQuery, SourceError
from openbb_finance.sources.tdx import TdxSource
from tdx_api.client import TdxService
from tdx_api.config import Config
from tdx_api.main import create_app
from tdx_api.tdx.commands.ex.extended import GetExInstrumentCountCmd, GetExInstrumentInfoCmd
from tdx_api.tdx.commands.mac.symbols import MacSymbolBarCmd, MacSymbolInfoCmd, MacSymbolQuotesCmd
from tdx_api.tdx.commands.standard.securities import GetSecurityCountCmd, GetSecurityListCmd
from tdx_api.tdx.enums import ExMarket, StdMarket
from tdx_api.tdx.models import ExInstrumentInfo, MacQuote, MacSymbolInfo

pytestmark = pytest.mark.anyio

SH_MARKET = int(StdMarket.SH)
INTL_INDEX_MARKET = int(ExMarket.INTL_INDEX)
CFFEX_MARKET = int(ExMarket.CFFEX_FUTURES)
SGE_MARKET = int(ExMarket.SH_GOLD)
GFEX_MARKET = int(ExMarket.GFEX_FUTURES)


# --------------------------------------------------------------------- #
# Command-level fake sessions (upstream socket replacement)
# --------------------------------------------------------------------- #


class FakeSession:
    def __init__(self, handlers: dict) -> None:
        self.handlers = handlers
        self.closed = False

    def execute(self, cmd):
        handler = self.handlers.get(type(cmd))
        if handler is None:
            raise AssertionError(f"unexpected command: {type(cmd).__name__}")
        return handler(cmd)

    def close(self) -> None:
        self.closed = True


def make_contract_source(handlers: dict, source_config: SourceConfig | None = None) -> TdxSource:
    service_config = Config(
        host="127.0.0.1",
        port=8011,
        api_key=None,
        connect_seconds=1.0,
        io_seconds=1.0,
        request_budget_seconds=10.0,
        max_host_switches=0,
        max_concurrency=8,
        queue_wait_seconds=0.2,
        quotes_batch_limit=80,
        max_page_limit=1000,
        cache_ttl_seconds=300.0,
        directory_max_entries=5000,
        hosts_standard=None,
        hosts_mac=None,
        hosts_mac_ex=None,
    )

    def factory(kind: str, host: str, budget) -> FakeSession:
        return FakeSession(handlers)

    app = create_app(service_config, service=TdxService(service_config, factory=factory))
    source_config = source_config or SourceConfig(name="tdx", enabled=True, base_url="http://tdx.test")
    return TdxSource(source_config, transport=httpx.ASGITransport(app=app))


def bar(day: datetime, close: float, vol: float) -> dict:
    return {
        "datetime": day,
        "open": close - 0.5,
        "high": close + 0.5,
        "low": close - 1.0,
        "close": close,
        "vol": vol,
        "amount": vol * 10,
    }


def kline_handlers(histories: dict[tuple[int, str], list[dict]]) -> dict:
    def handle(cmd: MacSymbolBarCmd):
        bars = histories.get((cmd.market, cmd.code), [])
        end = len(bars) - cmd.start
        return bars[max(end - cmd.count, 0) : end]

    return {MacSymbolBarCmd: handle}


# --------------------------------------------------------------------- #
# Klines
# --------------------------------------------------------------------- #


CN_BARS = [
    bar(datetime(2026, 6, 13), 1.5, 1000.0),
    bar(datetime(2026, 6, 16), 2.4, 2000.0),
]


async def test_cn_kline_contract_end_to_end():
    source = make_contract_source(kline_handlers({(SH_MARKET, "600519"): CN_BARS}))

    rows = await source.fetch_price(PriceQuery(symbol="600519.XSHG", market="cn", interval="1d"))

    # Real service schemas + real client normalization: dates, values, units.
    assert rows == [
        {
            "symbol": "600519.XSHG",
            "date": date(2026, 6, 13),
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "volume": 1000.0,  # CN klines already report shares
            "amount": 10000.0,
            "source": "tdx",
        },
        {
            "symbol": "600519.XSHG",
            "date": date(2026, 6, 16),
            "open": 1.9,
            "high": 2.9,
            "low": 1.4,
            "close": 2.4,
            "volume": 2000.0,
            "amount": 20000.0,
            "source": "tdx",
        },
    ]


async def test_cffex_main_continuous_contract_uses_l0():
    ifl_bars = [bar(datetime(2026, 6, 13), 3900.0, 120.0)]
    source = make_contract_source(kline_handlers({(CFFEX_MARKET, "IFL0"): ifl_bars}))

    rows = await source.fetch_price(PriceQuery(symbol="IF.CFFEX", market="future", interval="1d"))

    assert rows[0]["symbol"] == "IF.CFFEX"
    assert rows[0]["close"] == 3900.0


async def test_service_capability_error_maps_to_source_error():
    # SGE klines accept only raw prices: qfq is a real service-side 422.
    source = make_contract_source({})

    with pytest.raises(SourceError, match="unsupported_capability"):
        await source.fetch_price(PriceQuery(symbol="AU.SGE", market="future", interval="1d", adjusted=True))


# --------------------------------------------------------------------- #
# Quotes
# --------------------------------------------------------------------- #


def quote_handlers(quotes: list[MacQuote]) -> dict:
    def handle(cmd: MacSymbolQuotesCmd):
        wanted = set(cmd.stocks)
        return [quote for quote in quotes if (quote.market, quote.code) in wanted]

    return {MacSymbolQuotesCmd: handle}


async def test_cn_quote_contract_converts_lots_via_service_meta():
    quotes = [
        MacQuote(
            market=SH_MARKET,
            code="600519",
            name="贵州茅台",
            fields={
                "close": 1271.1,
                "pre_close": 1291.91,
                "open": 1292.7,
                "high": 1292.7,
                "low": 1270.1,
                "vol": 41585,
                "amount": 5.3e9,
            },
        )
    ]
    source = make_contract_source(quote_handlers(quotes))

    result = await source.fetch_quote("600519.XSHG")

    # The real service declares quote volume in lots with lot_size=100 for CN.
    assert result["last_price"] == 1271.1
    assert result["prev_close"] == 1291.91
    assert result["volume"] == 4_158_500.0
    assert result["change"] == pytest.approx(-20.81)


async def test_index_quote_contract_matches_native_code():
    # Regression: the service normalizes alias SPX -> A_SPX; the quote row
    # echoes the native code, and the consumer must match and send it.
    quotes = [
        MacQuote(
            market=INTL_INDEX_MARKET,
            code="A_SPX",
            name="标普500",
            fields={"close": 5300.0, "pre_close": 5290.0},
        )
    ]
    source = make_contract_source(quote_handlers(quotes))

    result = await source.fetch_quote("SPX")

    assert result["symbol"] == "SPX"
    assert result["last_price"] == 5300.0
    assert result["prev_close"] == 5290.0


# --------------------------------------------------------------------- #
# Equity info fast path
# --------------------------------------------------------------------- #


def info_handlers(found: dict[tuple[int, str], str]) -> dict:
    def handle(cmd: MacSymbolInfoCmd):
        name = found.get((cmd.market, cmd.code))
        if name is None:
            return None  # service maps this to data=null (normal miss)
        return MacSymbolInfo(
            market=cmd.market,
            code=cmd.code,
            name=name,
            time=None,
            pre_close=10.0,
            open=10.0,
            high=10.0,
            low=10.0,
            close=10.0,
            vol=100,
            amount=1000.0,
        )

    return {MacSymbolInfoCmd: handle}


async def test_equity_info_fast_path_contract():
    source = make_contract_source(info_handlers({(SH_MARKET, "600000"): "浦发银行"}))

    results = await source.fetch_equity_search("600000.SH", is_symbol=True)

    assert results == [{"symbol": "600000.XSHG", "name": "浦发银行", "exchange": "XSHG", "type": None, "source": "tdx"}]


async def test_equity_info_miss_maps_to_null_not_error():
    handlers = info_handlers({})
    # Miss falls back to the narrowed search: serve an empty CN directory.
    handlers[GetSecurityCountCmd] = lambda cmd: 0
    handlers[GetSecurityListCmd] = lambda cmd: []
    source = make_contract_source(handlers)

    results = await source.fetch_equity_search("600000.SH", is_symbol=True)

    # data=null on /instruments/info is a normal miss; the narrowed search then
    # also finds nothing.
    assert results == []


# --------------------------------------------------------------------- #
# Futures directory search
# --------------------------------------------------------------------- #


EX_ROWS = [
    ExInstrumentInfo(category=11, market=SGE_MARKET, code="Au(T+D)", name="Au(T+D)", desc=""),
    ExInstrumentInfo(category=3, market=GFEX_MARKET, code="SIL8", name="工业硅主连", desc=""),
    ExInstrumentInfo(category=3, market=GFEX_MARKET, code="SI2608", name="工业硅2608", desc=""),
]


def ex_directory_handlers(rows: list[ExInstrumentInfo]) -> dict:
    return {
        GetExInstrumentCountCmd: lambda cmd: len(rows),
        GetExInstrumentInfoCmd: lambda cmd: rows[cmd.start : cmd.start + cmd.count],
    }


async def test_futures_directory_search_contract():
    source = make_contract_source(ex_directory_handlers(EX_ROWS))

    results = await source.fetch_futures_search("SI", is_symbol=True)

    assert results == [
        {
            "symbol": "SI.GFEX",
            "expiration": "2026-08",
            "code": "SI2608",
            "name": "工业硅2608",
            "exchange": "GFEX",
            "source": "tdx",
        },  # noqa: E501
        {
            "symbol": "SI.GFEX",
            "expiration": None,
            "code": "SIL8",
            "name": "工业硅主连",
            "exchange": "GFEX",
            "source": "tdx",
        },
    ]


async def test_futures_directory_sge_alias_contract():
    source = make_contract_source(ex_directory_handlers(EX_ROWS))

    results = await source.fetch_futures_search("AU", is_symbol=False)

    assert results == [
        {
            "symbol": "AU.SGE",
            "expiration": None,
            "code": "Au(T+D)",
            "name": "Au(T+D)",
            "exchange": "SGE",
            "source": "tdx",
        }
    ]


# --------------------------------------------------------------------- #
# Router fallback with a real failing source
# --------------------------------------------------------------------- #


async def test_real_tdx_source_failure_falls_through_to_next_source():
    # Real TdxSource pointed at a dead local port: SourceError must move the
    # router to the next source and return its data.
    failing = TdxSource(SourceConfig(name="tdx", enabled=True, base_url="http://127.0.0.1:9"))

    class FallbackSource:
        name = "tickflow"

        async def fetch_price(self, query):
            return [
                {
                    "symbol": query.symbol,
                    "date": date(2026, 4, 24),
                    "open": 1.0,
                    "high": 2.0,
                    "low": 0.5,
                    "close": 1.5,
                    "volume": 100,
                    "source": "tickflow",
                }
            ]

    class Registry:
        def ordered_by_names(self, names):
            assert names[0] == "tdx"  # routing order preserved
            return [failing, FallbackSource()]

    data = await FinanceEquityHistoricalFetcher.aextract_data(
        FinanceEquityHistoricalFetcher.transform_query({"symbol": "600519.XSHG"}),
        credentials=None,
        registry=Registry(),
    )

    assert data[0]["source"] == "tickflow"
