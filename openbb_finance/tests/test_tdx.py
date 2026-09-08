"""TdxSource tests: HTTP contract doubles via httpx.MockTransport.

The double mimics the tdx-api envelope contract ({"data", "meta"}, error
envelopes, FastAPI 401 detail) so the source is exercised through real HTTP
serialization. Cross-package ASGI coverage against the real service lives in
test_tdx_http_contract.py.
"""

from datetime import date, datetime, timedelta
from typing import Any

import httpx
import pytest
from openbb_finance.config import SourceConfig
from openbb_finance.sources.base import PriceQuery, SourceError
from openbb_finance.sources.tdx import (
    TdxSource,
    _futures_contract_symbol,
    _is_queryable_futures_code,
    _service_interval,
    _to_futures_market,
    _to_service_market,
)

pytestmark = pytest.mark.anyio

BASE_URL = "http://tdx.test"
API_KEY = "tdx-secret"


def bar(day: str, *, close: float = 10.0, volume: float = 100.0, minute: str | None = None) -> dict:
    payload = {
        "datetime": f"{day}T{minute}" if minute else day,
        "trade_date": day,
        "open": close - 0.5,
        "high": close + 0.5,
        "low": close - 1.0,
        "close": close,
        "volume": volume,
        "amount": 1000.0,
    }
    return payload


def envelope(data, meta=None) -> dict:
    return {"data": data, "meta": meta or {}}


def kline_envelope(rows: list[dict], *, offset: int = 0, complete: bool | None = None) -> dict:
    """Envelope with service-shaped paging meta for a kline page."""
    limit = 1000
    exhausted = len(rows) < limit if complete is None else complete
    return envelope(
        rows,
        meta={
            "offset": offset,
            "limit": limit,
            "count": len(rows),
            "complete": exhausted,
            "next_offset": offset + len(rows) if len(rows) >= limit and not exhausted else None,
        },
    )


class FakeTdxApi:
    """Route table of path -> handler(query params) -> (status, json payload)."""

    def __init__(self, routes: dict[str, Any] | None = None):
        self.calls: list[tuple[str, dict[str, str], httpx.Headers]] = []
        self.routes = routes or {}

    def handle(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.calls.append((request.url.path, params, request.headers))
        handler = self.routes.get(request.url.path)
        if handler is None:
            return httpx.Response(404, json={"error": {"code": "not_found", "message": request.url.path}})
        status, payload = handler(params)
        if isinstance(payload, bytes):
            return httpx.Response(status, content=payload)
        return httpx.Response(status, json=payload)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)


def make_source(
    routes: dict | None = None,
    *,
    base_url: str | None = BASE_URL,
    api_key: str | None = API_KEY,
    enabled: bool = True,
    transport: httpx.AsyncBaseTransport | None = None,
) -> TdxSource:
    config = SourceConfig(
        name="tdx",
        enabled=enabled,
        base_url=base_url,
        api_key=api_key,
    )
    return TdxSource(config, transport=transport or (FakeTdxApi(routes).transport() if routes else None))


# --------------------------------------------------------------------- #
# Market / symbol mapping
# --------------------------------------------------------------------- #


def test_cn_symbols_map_to_service_markets():
    assert _to_service_market("600519.XSHG", "cn") == ("cn_sh", "600519")
    assert _to_service_market("000001.SZ", "cn") == ("cn_sz", "000001")
    assert _to_service_market("600519", "cn") == ("cn_sh", "600519")


def test_hk_symbols_pad_and_split_gem():
    assert _to_service_market("700.HK", "hk") == ("hk", "00700")
    assert _to_service_market("8001.HK", "hk") == ("hk_gem", "08001")
    assert _to_service_market("00700", "hk") == ("hk", "00700")


def test_us_symbols_keep_internal_dots():
    assert _to_service_market("AAPL", "us") == ("us", "AAPL")
    # Only recognized exchange suffixes strip; US dotted codes stay whole.
    assert _to_service_market("BRK.B", "us") == ("us", "BRK.B")


def test_index_aliases_map_to_index_markets():
    # Values are the service-native codes: the service normalizes aliases to
    # them and quote rows echo the native code back, so matching must use it.
    assert _to_service_market("SPX", "us") == ("intl_index", "A_SPX")
    assert _to_service_market("NDX", "us") == ("intl_index", "A_NDX")
    assert _to_service_market("HSI", "hk") == ("hk_index", "HSI")
    assert _to_service_market("HSCEI", "hk") == ("hk_index", "HZ5014")
    assert _to_service_market("HSTECH", "hk") == ("hk_index", "HZ5017")


def test_futures_market_translation_domestic():
    assert _to_futures_market("rb.SHFE") == ("shfe", "RBL8")
    assert _to_futures_market("rb.SHFE", "2026-10") == ("shfe", "RB2610")
    # CFFEX main continuous is L0 per the service README/live contract.
    assert _to_futures_market("IF.CFFEX") == ("cffex", "IFL0")
    assert _to_futures_market("IF.CFFEX", "2026-12") == ("cffex", "IF2612")
    assert _to_futures_market("si.GFEX", "2026-08") == ("gfex", "SI2608")
    assert _to_futures_market("M.DCE") == ("dce", "ML8")
    assert _to_futures_market("SR.CZCE") == ("czce", "SRL8")


def test_futures_market_translation_international_month_letter():
    assert _to_futures_market("GC.COMEX") == ("comex", "GC00W")
    assert _to_futures_market("GC.COMEX", "2026-12") == ("comex", "GC26Z")
    assert _to_futures_market("GC.COMEX", "2026-01") == ("comex", "GC26F")
    assert _to_futures_market("CL.NYMEX") == ("nymex", "CL00W")
    assert _to_futures_market("ZL.CBOT", "2026-07") == ("cbot", "ZL26N")


def test_futures_market_translation_sge_fixed_map():
    assert _to_futures_market("AU.SGE") == ("sge", "Au(T+D)")
    assert _to_futures_market("AG.SGE") == ("sge", "Ag(T+D)")
    assert _to_futures_market("AU9999.SGE") == ("sge", "Au99.99")
    # SGE ignores expiration (no month contracts).
    assert _to_futures_market("AU.SGE", "2026-12") == ("sge", "Au(T+D)")


def test_futures_market_translation_rejects_bad_input():
    with pytest.raises(SourceError):
        _to_futures_market("XYZ.SGE")
    with pytest.raises(SourceError):
        _to_futures_market("RB.UNKNOWN")
    with pytest.raises(SourceError):
        _to_futures_market("GC.COMEX", "2026-13")
    with pytest.raises(SourceError):
        _to_futures_market("GC.COMEX", "26-12")
    with pytest.raises(SourceError):
        _to_service_market("AAPL", "cn")


def test_futures_contract_symbol_round_trips_tdx_codes():
    assert _futures_contract_symbol("SHFE", "RBL8") == ("RB.SHFE", None)
    assert _futures_contract_symbol("SHFE", "RB2610") == ("RB.SHFE", "2026-10")
    assert _futures_contract_symbol("GFEX", "SIL8") == ("SI.GFEX", None)
    assert _futures_contract_symbol("GFEX", "SI2608") == ("SI.GFEX", "2026-08")
    assert _futures_contract_symbol("COMEX", "GC00W") == ("GC.COMEX", None)
    assert _futures_contract_symbol("COMEX", "GC26Z") == ("GC.COMEX", "2026-12")
    assert _futures_contract_symbol("SGE", "Au(T+D)") == ("AU.SGE", None)
    assert _futures_contract_symbol("CFFEX", "IFL0") == ("IF.CFFEX", None)
    assert _futures_contract_symbol("CFFEX", "IF2612") == ("IF.CFFEX", "2026-12")


def test_queryable_futures_code_filters_auxiliary_continuous():
    assert _is_queryable_futures_code("SHFE", "RBL8")
    assert not _is_queryable_futures_code("SHFE", "RBL7")  # 次连
    assert not _is_queryable_futures_code("SHFE", "RBL9")  # 加权
    assert _is_queryable_futures_code("SHFE", "RB2610")
    assert _is_queryable_futures_code("COMEX", "GC00W")
    assert not _is_queryable_futures_code("COMEX", "GC00Y")  # 连续
    assert _is_queryable_futures_code("COMEX", "GC26Z")
    assert _is_queryable_futures_code("CFFEX", "IFL0")
    assert not _is_queryable_futures_code("CFFEX", "IFL8")
    assert _is_queryable_futures_code("SGE", "Au(T+D)")


def test_service_interval_mapping():
    assert _service_interval("1") == "1m"
    assert _service_interval("5m") == "5m"
    assert _service_interval("60") == "60m"
    assert _service_interval("1h") == "60m"
    assert _service_interval("1d") == "1d"
    assert _service_interval("1w") == "1w"
    # "1M" is monthly; the minute set must not swallow it case-insensitively.
    assert _service_interval("1M") == "1M"
    with pytest.raises(SourceError):
        _service_interval("2m")


# --------------------------------------------------------------------- #
# Configuration gating
# --------------------------------------------------------------------- #


def test_tdx_disabled_without_base_url():
    assert make_source(base_url=None).enabled is False
    assert make_source(base_url="   ").enabled is False
    assert make_source(base_url=BASE_URL, enabled=False).enabled is False
    assert make_source(base_url=BASE_URL).enabled is True


async def test_missing_base_url_raises_clear_source_error():
    source = make_source(base_url=None)
    with pytest.raises(SourceError, match="TDX_API_BASE_URL"):
        await source.fetch_price(PriceQuery(symbol="600519.XSHG", market="cn"))


async def test_invalid_scheme_rejected_at_fetch_time():
    source = make_source(base_url="ftp://tdx.test")
    assert source.enabled is True  # construction stays non-raising
    with pytest.raises(SourceError, match="must be an http"):
        await source.fetch_price(PriceQuery(symbol="600519.XSHG", market="cn"))


async def test_trailing_slash_base_url_and_api_key_header():
    api = FakeTdxApi({"/api/v1/klines": lambda params: (200, kline_envelope([bar("2026-06-13")]))})
    source = make_source(
        routes=None,
        base_url=f"{BASE_URL}/",
        api_key=API_KEY,
        transport=httpx.MockTransport(api.handle),
    )
    await source.fetch_price(PriceQuery(symbol="600519.XSHG", market="cn"))

    path, params, headers = api.calls[0]
    assert path == "/api/v1/klines"
    assert headers.get("X-API-Key") == API_KEY
    assert params["market"] == "cn_sh"
    assert params["code"] == "600519"


# --------------------------------------------------------------------- #
# Klines
# --------------------------------------------------------------------- #


async def test_cn_price_sends_qfq_and_filters_date_window():
    rows = [
        bar("2026-06-13", close=1255.0, volume=1000),
        bar("2026-06-15", close=1271.1, volume=41585),
    ]
    api = FakeTdxApi({"/api/v1/klines": lambda params: (200, kline_envelope(rows))})
    source = make_source(transport=api.transport())

    result = await source.fetch_price(
        PriceQuery(
            symbol="600519.XSHG",
            market="cn",
            start_date=date(2026, 6, 15),
            end_date=date(2026, 6, 15),
            interval="1d",
            adjusted=True,
        )
    )

    path, params, _headers = api.calls[0]
    assert path == "/api/v1/klines"
    assert params == {
        "market": "cn_sh",
        "code": "600519",
        "interval": "1d",
        "adjust": "qfq",
        "offset": "0",
        "limit": "1000",
    }
    assert result == [
        {
            "symbol": "600519.XSHG",
            "date": date(2026, 6, 15),
            "open": 1270.6,
            "high": 1271.6,
            "low": 1270.1,
            "close": 1271.1,
            "volume": 41585.0,
            "amount": 1000.0,
            "source": "tdx",
        }
    ]


async def test_kline_volume_preserves_zero_and_null():
    rows = [
        {
            "datetime": "2026-06-13",
            "trade_date": "2026-06-13",
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 0.0,
            "volume": 0,
            "amount": None,
        },
        {
            "datetime": "2026-06-14",
            "trade_date": "2026-06-14",
            "open": None,
            "high": None,
            "low": None,
            "close": None,
            "volume": None,
            "amount": None,
        },
    ]
    source = make_source({"/api/v1/klines": lambda params: (200, kline_envelope(rows))})

    result = await source.fetch_price(PriceQuery(symbol="600519.XSHG", market="cn"))

    assert result[0]["close"] == 0.0
    assert result[0]["volume"] == 0.0
    assert result[0]["amount"] is None
    assert result[1]["close"] is None
    assert result[1]["volume"] is None


async def test_hk_price_zero_pads_code_and_keeps_minute_datetime_and_raw_volume():
    rows = [bar("2026-06-15", close=297.05, volume=100, minute="09:31:00")]
    api = FakeTdxApi({"/api/v1/klines": lambda params: (200, kline_envelope(rows))})
    source = make_source(transport=api.transport())

    result = await source.fetch_price(PriceQuery(symbol="700.HK", market="hk", interval="1m"))

    _, params, _headers = api.calls[0]
    assert params["market"] == "hk"
    assert params["code"] == "00700"
    assert params["interval"] == "1m"
    assert params["adjust"] == "none"
    assert result[0]["date"] == datetime(2026, 6, 15, 9, 31)
    assert result[0]["symbol"] == "700.HK"
    # Service HK kline volume is board lots and passes through untouched
    # (the legacy fixed x100 multiplier is gone).
    assert result[0]["volume"] == 100.0


async def test_us_price_preserves_dotted_symbol():
    api = FakeTdxApi({"/api/v1/klines": lambda params: (200, kline_envelope([bar("2026-06-13")]))})
    source = make_source(transport=api.transport())

    result = await source.fetch_price(PriceQuery(symbol="BRK.B", market="us", interval="5m"))

    _, params, _headers = api.calls[0]
    assert params["market"] == "us"
    assert params["code"] == "BRK.B"
    assert result[0]["symbol"] == "BRK.B"


async def test_futures_price_uses_main_continuous_and_month_codes():
    api = FakeTdxApi({"/api/v1/klines": lambda params: (200, kline_envelope([bar("2026-06-13")]))})
    source = make_source(transport=api.transport())

    result = await source.fetch_price(PriceQuery(symbol="rb.SHFE", market="future", interval="1d"))
    _, params, _headers = api.calls[0]
    assert (params["market"], params["code"]) == ("shfe", "RBL8")
    assert result[0]["symbol"] == "RB.SHFE"
    assert result[0]["source"] == "tdx"

    await source.fetch_price(PriceQuery(symbol="GC.COMEX", market="future", expiration="2026-12", interval="1d"))
    _, params, _headers = api.calls[1]
    assert (params["market"], params["code"]) == ("comex", "GC26Z")


async def test_cffex_price_uses_l0_main_continuous():
    api = FakeTdxApi({"/api/v1/klines": lambda params: (200, kline_envelope([bar("2026-06-13")]))})
    source = make_source(transport=api.transport())

    await source.fetch_price(PriceQuery(symbol="IF.CFFEX", market="future", interval="1d"))

    _, params, _headers = api.calls[0]
    assert (params["market"], params["code"]) == ("cffex", "IFL0")


async def test_index_price_uses_index_markets():
    api = FakeTdxApi({"/api/v1/klines": lambda params: (200, kline_envelope([bar("2026-06-13")]))})
    source = make_source(transport=api.transport())

    await source.fetch_price(PriceQuery(symbol="SPX", market="us", interval="1d"))
    _, params, _headers = api.calls[0]
    assert (params["market"], params["code"]) == ("intl_index", "A_SPX")

    await source.fetch_price(PriceQuery(symbol="HSTECH", market="hk", interval="1d"))
    _, params, _headers = api.calls[1]
    assert (params["market"], params["code"]) == ("hk_index", "HZ5017")


async def test_adjusted_on_unsupported_market_surfaces_service_422():
    api = FakeTdxApi(
        {
            "/api/v1/klines": lambda params: (
                422,
                {"error": {"code": "unsupported_capability", "message": "市场 shfe 支持的复权方式: ['none']"}},
            )
        }
    )
    source = make_source(transport=api.transport())

    with pytest.raises(SourceError, match="unsupported_capability"):
        await source.fetch_price(PriceQuery(symbol="rb.SHFE", market="future", interval="1d", adjusted=True))


# --------------------------------------------------------------------- #
# Quotes
# --------------------------------------------------------------------- #


def quote_row(**overrides) -> dict:
    row = {
        "market": "cn_sh",
        "code": "600519",
        "name": "贵州茅台",
        "price": 1271.1,
        "pre_close": 1291.91,
        "open": 1292.7,
        "high": 1292.7,
        "low": 1270.1,
        "volume": 41585,
        "amount": 5_303_655_936.0,
    }
    row.update(overrides)
    return row


async def test_cn_quote_converts_lot_volume_via_service_meta():
    api = FakeTdxApi(
        {
            "/api/v1/quotes": lambda params: (
                200,
                envelope(
                    [quote_row()],
                    meta={"market": "cn_sh", "volume_unit": "lot", "lot_size": 100},
                ),
            )
        }
    )
    source = make_source(transport=api.transport())

    result = await source.fetch_quote("600519.XSHG")

    path, params, _headers = api.calls[0]
    assert path == "/api/v1/quotes"
    assert params == {"market": "cn_sh", "codes": "600519"}
    assert result["symbol"] == "600519.XSHG"
    assert result["last_price"] == 1271.1
    assert result["prev_close"] == 1291.91
    assert result["volume"] == 4_158_500.0
    assert result["change"] == pytest.approx(-20.81)
    assert result["change_percent"] == pytest.approx(-1.6107925466959658)
    assert result["source"] == "tdx"


async def test_us_quote_keeps_raw_volume_without_lot_meta():
    api = FakeTdxApi(
        {
            "/api/v1/quotes": lambda params: (
                200,
                envelope(
                    [
                        quote_row(
                            market="us", code="AAPL", name="苹果", price=297.28, pre_close=291.13, volume=17_429_069
                        )
                    ],
                    meta={"market": "us", "volume_unit": None, "lot_size": None},
                ),
            )
        }
    )
    source = make_source(transport=api.transport())

    result = await source.fetch_quote("AAPL")

    assert result["symbol"] == "AAPL"
    assert result["last_price"] == 297.28
    assert result["volume"] == 17_429_069.0


async def test_futures_quote_includes_name_and_raw_volume():
    api = FakeTdxApi(
        {
            "/api/v1/quotes": lambda params: (
                200,
                envelope(
                    [
                        quote_row(
                            market="sge", code="Au(T+D)", name="黄金延期", price=560.0, pre_close=558.0, volume=12_345
                        )
                    ],
                    meta={"market": "sge", "volume_unit": None, "lot_size": None},
                ),
            )
        }
    )
    source = make_source(transport=api.transport())

    result = await source.fetch_quote("AU.SGE")

    _, params, _headers = api.calls[0]
    assert params == {"market": "sge", "codes": "Au(T+D)"}
    assert result["symbol"] == "AU.SGE"
    assert result["name"] == "黄金延期"
    assert result["last_price"] == 560.0
    assert result["volume"] == 12_345.0


async def test_quote_empty_rows_raise():
    source = make_source({"/api/v1/quotes": lambda params: (200, envelope([], meta={}))})
    with pytest.raises(SourceError, match="no data"):
        await source.fetch_quote("600519.XSHG")


async def test_quote_target_mismatch_raises():
    source = make_source(
        {
            "/api/v1/quotes": lambda params: (
                200,
                envelope([quote_row(code="600000")], meta={}),
            )
        }
    )
    with pytest.raises(SourceError, match="did not include"):
        await source.fetch_quote("600519.XSHG")


async def test_index_quote_matches_native_code_row():
    # Regression: the service normalizes SPX -> A_SPX and the quote row echoes
    # the native code from the wire; the consumer must match on it.
    api = FakeTdxApi(
        {
            "/api/v1/quotes": lambda params: (
                200,
                envelope(
                    [quote_row(market="intl_index", code="A_SPX", name="S&P 500", price=5300.0, pre_close=5290.0)],
                    meta={"market": "intl_index"},
                ),
            )
        }
    )
    source = make_source(transport=api.transport())

    result = await source.fetch_quote("SPX")

    _, params, _headers = api.calls[0]
    assert params == {"market": "intl_index", "codes": "A_SPX"}
    assert result["symbol"] == "SPX"
    assert result["last_price"] == 5300.0


async def test_quote_zero_price_preserved():
    api = FakeTdxApi(
        {
            "/api/v1/quotes": lambda params: (
                200,
                envelope([quote_row(price=0, pre_close=0, volume=0)], meta={"market": "cn_sh"}),
            )
        }
    )
    source = make_source(transport=api.transport())

    result = await source.fetch_quote("600519.XSHG")

    # Zero must survive (never collapse to None); change stays None (prev=0).
    assert result["last_price"] == 0.0
    assert result["prev_close"] == 0.0
    assert result["volume"] == 0.0
    assert result["change"] is None


async def test_kline_rejects_inverted_date_range():
    api = FakeTdxApi({"/api/v1/klines": lambda params: (200, kline_envelope([bar("2026-06-13")]))})
    source = make_source(transport=api.transport())

    with pytest.raises(SourceError, match="invalid date range"):
        await source.fetch_price(
            PriceQuery(symbol="600519.XSHG", market="cn", start_date=date(2026, 6, 15), end_date=date(2026, 6, 13))
        )
    assert api.calls == []  # rejected before any HTTP request


# --------------------------------------------------------------------- #
# HTTP error mapping
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("status", "payload", "expected_fragment"),
    [
        (401, {"detail": "invalid or missing X-API-Key"}, "401"),
        (
            422,
            {"error": {"code": "invalid_parameter", "message": "未知 market: 'xx'"}},
            "invalid_parameter",
        ),
        (
            503,
            {"error": {"code": "upstream_unavailable", "message": "候选主机均不可用"}},
            "upstream_unavailable",
        ),
        (504, {"error": {"code": "budget_exceeded", "message": "请求总预算耗尽"}}, "budget_exceeded"),
    ],
)
async def test_http_error_statuses_map_to_source_error(status, payload, expected_fragment):
    source = make_source({"/api/v1/klines": lambda params: (status, payload)})

    with pytest.raises(SourceError, match=expected_fragment):
        await source.fetch_price(PriceQuery(symbol="600519.XSHG", market="cn"))


async def test_error_envelope_on_http_200_fails_loudly():
    source = make_source(
        {"/api/v1/klines": lambda params: (200, {"error": {"code": "upstream_data_error", "message": "bad frame"}})}
    )

    with pytest.raises(SourceError, match="upstream_data_error"):
        await source.fetch_price(PriceQuery(symbol="600519.XSHG", market="cn"))


async def test_invalid_json_maps_to_source_error():
    source = make_source({"/api/v1/klines": lambda params: (200, b"not json")})

    with pytest.raises(SourceError, match="invalid JSON"):
        await source.fetch_price(PriceQuery(symbol="600519.XSHG", market="cn"))


@pytest.mark.parametrize(
    "payload",
    [
        {"meta": {}},  # missing data
        {"data": []},  # missing meta
        {"data": "nope", "meta": {}},  # wrong data type
        {"data": [None], "meta": {}},  # malformed row
    ],
)
async def test_malformed_envelopes_map_to_source_error(payload):
    source = make_source({"/api/v1/klines": lambda params: (200, payload)})

    with pytest.raises(SourceError, match="malformed|missing data/meta"):
        await source.fetch_price(PriceQuery(symbol="600519.XSHG", market="cn"))


async def test_network_failure_hides_base_url_and_credentials():
    def raise_connect_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    source = make_source(transport=httpx.MockTransport(raise_connect_error))

    with pytest.raises(SourceError, match="request failed") as exc_info:
        await source.fetch_price(PriceQuery(symbol="600519.XSHG", market="cn"))
    message = str(exc_info.value)
    assert BASE_URL not in message
    assert API_KEY not in message


# --------------------------------------------------------------------- #
# Kline pagination (bounded history)
# --------------------------------------------------------------------- #


def history_bars(count: int, *, start: date = date(2024, 1, 1)) -> list[dict]:
    """Ascending daily history: index 0 = oldest, index count-1 = newest."""
    return [bar((start + timedelta(days=i)).isoformat(), close=10.0 + i) for i in range(count)]


def paginated_klines(history: list[dict], *, page_cap: int = 1000, complete: bool | None = None):
    """Service-shaped offset paging: offset counts back from the newest bar."""

    def handler(params: dict) -> tuple[int, object]:
        offset = int(params["offset"])
        limit = min(int(params["limit"]), page_cap)
        end = len(history) - offset
        page = history[max(end - limit, 0) : end] if end > 0 else []
        exhausted = len(page) < limit if complete is None else complete
        return 200, envelope(
            page,
            meta={
                "offset": offset,
                "limit": limit,
                "count": len(page),
                "complete": exhausted,
                "next_offset": offset + len(page) if len(page) >= limit and exhausted is False else None,
            },
        )

    return {"/api/v1/klines": handler}


async def test_kline_pagination_covers_start_date_across_pages():
    history = history_bars(1500)
    api = FakeTdxApi(paginated_klines(history))
    source = make_source(transport=api.transport())
    start = date(2024, 1, 1) + timedelta(days=300)  # inside page 2 only

    result = await source.fetch_price(PriceQuery(symbol="600519.XSHG", market="cn", start_date=start, interval="1d"))

    offsets = [int(params["offset"]) for _path, params, _h in api.calls]
    assert offsets == [0, 1000]
    assert [row["date"] for row in result] == [date(2024, 1, 1) + timedelta(days=i) for i in range(300, 1500)]
    assert result[0]["date"] == start


async def test_kline_default_window_returns_newest_700_from_single_page():
    history = history_bars(1500)
    api = FakeTdxApi(paginated_klines(history))
    source = make_source(transport=api.transport())

    result = await source.fetch_price(PriceQuery(symbol="600519.XSHG", market="cn"))

    assert len(api.calls) == 1
    assert len(result) == 700
    assert result[0]["date"] == date(2024, 1, 1) + timedelta(days=800)
    assert result[-1]["date"] == date(2024, 1, 1) + timedelta(days=1499)


async def test_kline_end_date_only_looks_back_for_700_bars():
    history = history_bars(1500)
    api = FakeTdxApi(paginated_klines(history))
    source = make_source(transport=api.transport())
    end = date(2024, 1, 1) + timedelta(days=800)

    result = await source.fetch_price(PriceQuery(symbol="600519.XSHG", market="cn", end_date=end))

    offsets = [int(params["offset"]) for _path, params, _h in api.calls]
    assert offsets == [0, 1000]
    assert len(result) == 700
    assert result[-1]["date"] == end


async def test_kline_short_history_returns_everything_available():
    history = history_bars(300)
    api = FakeTdxApi(paginated_klines(history))
    source = make_source(transport=api.transport())

    result = await source.fetch_price(PriceQuery(symbol="600519.XSHG", market="cn"))

    assert len(api.calls) == 1
    assert len(result) == 300


async def test_kline_follows_service_lowered_page_limit():
    history = history_bars(1200)
    api = FakeTdxApi(paginated_klines(history, page_cap=500))  # admin-capped service
    source = make_source(transport=api.transport())
    start = date(2024, 1, 1) + timedelta(days=100)

    result = await source.fetch_price(PriceQuery(symbol="600519.XSHG", market="cn", start_date=start, interval="1d"))

    offsets = [int(params["offset"]) for _path, params, _h in api.calls]
    assert offsets == [0, 500, 1000]
    assert [row["date"] for row in result] == [date(2024, 1, 1) + timedelta(days=i) for i in range(100, 1200)]


async def test_kline_complete_flag_stops_paging_even_with_next_offset():
    history = history_bars(2000)
    api = FakeTdxApi(paginated_klines(history, complete=True))
    source = make_source(transport=api.transport())
    start = date(2024, 1, 1) + timedelta(days=100)  # far beyond page 1

    result = await source.fetch_price(PriceQuery(symbol="600519.XSHG", market="cn", start_date=start, interval="1d"))

    assert len(api.calls) == 1  # service-declared history end wins
    assert result[0]["date"] == date(2024, 1, 1) + timedelta(days=1000)


async def test_kline_boundary_overlap_dedup_keeps_first_received():
    history = history_bars(1500)

    def handler(params: dict) -> tuple[int, object]:
        offset = int(params["offset"])
        limit = int(params["limit"])
        if offset == 0:
            page, exhausted = history[500:1500], False
        else:
            # Data shifted: page 2 re-serves the boundary bar (index 500).
            page, exhausted = history[0:501], True
        return 200, envelope(
            page,
            meta={
                "offset": offset,
                "limit": limit,
                "count": len(page),
                "complete": exhausted,
                "next_offset": None if exhausted else offset + len(page),
            },
        )

    api = FakeTdxApi({"/api/v1/klines": handler})
    source = make_source(transport=api.transport())

    result = await source.fetch_price(
        PriceQuery(symbol="600519.XSHG", market="cn", start_date=date(2022, 1, 1), interval="1d")
    )

    dates = [row["date"] for row in result]
    assert len(dates) == len(set(dates))
    assert dates == sorted(dates)
    assert len(result) == 1500


async def test_kline_regressed_cursor_raises():
    def handler(params: dict) -> tuple[int, object]:
        offset = int(params["offset"])
        meta = {"offset": offset, "limit": 1000, "count": 1000, "complete": False, "next_offset": offset}
        return 200, envelope(history_bars(1000), meta)

    source = make_source({"/api/v1/klines": handler})

    with pytest.raises(SourceError, match="cursor is missing or regressed"):
        await source.fetch_price(
            PriceQuery(symbol="600519.XSHG", market="cn", start_date=date(2020, 1, 1), interval="1d")
        )


async def test_kline_stalled_page_without_new_bars_raises():
    page = history_bars(1000)

    def handler(params: dict) -> tuple[int, object]:
        offset = int(params["offset"])
        meta = {"offset": offset, "limit": 1000, "count": 1000, "complete": False, "next_offset": offset + 1000}
        return 200, envelope(page, meta)  # same bars every page

    source = make_source({"/api/v1/klines": handler})

    with pytest.raises(SourceError, match="did not advance"):
        await source.fetch_price(
            PriceQuery(symbol="600519.XSHG", market="cn", start_date=date(2020, 1, 1), interval="1d")
        )


async def test_kline_empty_incomplete_page_raises():
    calls = {"n": 0}

    def handler(params: dict) -> tuple[int, object]:
        offset = int(params["offset"])
        calls["n"] += 1
        if offset == 0:
            meta = {"offset": offset, "limit": 1000, "count": 1000, "complete": False, "next_offset": 1000}
            return 200, envelope(history_bars(1000), meta)
        meta = {"offset": offset, "limit": 1000, "count": 0, "complete": False, "next_offset": None}
        return 200, envelope([], meta)

    source = make_source({"/api/v1/klines": handler})

    with pytest.raises(SourceError, match="empty page with an incomplete status"):
        await source.fetch_price(
            PriceQuery(symbol="600519.XSHG", market="cn", start_date=date(2020, 1, 1), interval="1d")
        )


async def test_kline_page_budget_exhaustion_raises_instead_of_truncating():
    history = history_bars(25_000)
    api = FakeTdxApi(paginated_klines(history))
    source = make_source(transport=api.transport())
    start = date(2020, 1, 1)  # unreachable within the page budget

    with pytest.raises(SourceError, match="20-page budget"):
        await source.fetch_price(PriceQuery(symbol="600519.XSHG", market="cn", start_date=start, interval="1d"))
    assert len(api.calls) == 20
    # No truncated partial history escaped as success.


async def test_kline_wall_clock_budget_exhaustion_raises(monkeypatch):
    import asyncio as _asyncio

    from openbb_finance.sources import tdx as tdx_module

    monkeypatch.setattr(tdx_module, "FETCH_BUDGET_SECONDS", 0.05)

    async def slow_handle(request: httpx.Request) -> httpx.Response:
        await _asyncio.sleep(1.0)  # upstream stall longer than the budget
        return httpx.Response(200, json=kline_envelope(history_bars(10)))

    source = make_source(transport=httpx.MockTransport(slow_handle))

    with pytest.raises(SourceError, match="budget"):
        await source.fetch_price(PriceQuery(symbol="600519.XSHG", market="cn"))


@pytest.mark.parametrize(
    ("meta_override", "expected"),
    [
        ({"offset": 999}, "does not match the requested offset"),
        ({"limit": 0}, "invalid limit"),
        ({"count": 5}, "does not match the returned"),
        ({"complete": None}, "complete flag"),
        ({"next_offset": "later"}, "invalid next_offset"),
    ],
)
async def test_kline_meta_contract_violations_raise(meta_override, expected):
    def handler(params: dict) -> tuple[int, object]:
        meta = {
            "offset": 0,
            "limit": 1000,
            "count": 2,
            "complete": True,
            "next_offset": None,
        }
        meta.update(meta_override)
        return 200, envelope(history_bars(2), meta)

    source = make_source({"/api/v1/klines": handler})

    with pytest.raises(SourceError, match=expected):
        await source.fetch_price(PriceQuery(symbol="600519.XSHG", market="cn"))


# --------------------------------------------------------------------- #
# Search: futures directory + cross-market equity
# --------------------------------------------------------------------- #


def instrument(market: str, code: str, name: str | None = None, desc: str | None = None) -> dict:
    row: dict = {"market": market, "code": code, "name": name}
    if desc is not None:
        row["desc"] = desc
    return row


def empty_page_meta(offset: int, count: int, *, complete: bool, directory_complete=True) -> dict:
    return {
        "offset": offset,
        "limit": 1000,
        "count": count,
        "complete": complete,
        "next_offset": None if complete else offset + count,
        "directory_complete": directory_complete,
    }


def search_route(pages_by_market: dict, *, directory_complete=True) -> dict:
    """Route /instruments/search: market -> list of pages of matching rows."""

    def handler(params: dict) -> tuple[int, object]:
        market = params["market"]
        pages = pages_by_market[market]
        if isinstance(pages, tuple):
            return pages
        offset = int(params["offset"])
        page_index = offset // 1000
        page = pages[page_index] if page_index < len(pages) else []
        complete = page_index >= len(pages) - 1
        meta = empty_page_meta(offset, len(page), complete=complete, directory_complete=directory_complete)
        return 200, envelope(page, meta)

    return {"/api/v1/instruments/search": handler}


def instruments_route(rows_by_market: dict, *, directory_complete=True, page_cap: int = 1000) -> dict:
    """Route /instruments: market -> full directory, offset-sliced ascending."""

    def handler(params: dict) -> tuple[int, object]:
        market = params["market"]
        rows = rows_by_market[market]
        if isinstance(rows, tuple):
            return rows
        offset = int(params["offset"])
        limit = min(int(params["limit"]), page_cap)
        page = rows[offset : offset + limit]
        exhausted = offset + len(page) >= len(rows)
        meta = empty_page_meta(offset, len(page), complete=exhausted, directory_complete=directory_complete)
        return 200, envelope(page, meta)

    return {"/api/v1/instruments": handler}


def futures_directory_routes(**by_market) -> dict:
    base = {market: [] for market in FUTURES_SEARCH_TARGETS}
    base.update(by_market)
    return instruments_route(base)


def info_route(by_market_code: dict) -> dict:
    def handler(params: dict) -> tuple[int, object]:
        data = by_market_code.get((params["market"], params["code"]))
        return 200, envelope(data)

    return {"/api/v1/instruments/info": handler}


FUTURES_SEARCH_TARGETS = ("shfe", "dce", "czce", "gfex", "comex", "nymex", "cbot", "sge")
EQ_SEARCH_TARGETS = ("cn_sh", "cn_sz", "hk", "hk_gem", "us")


async def test_futures_search_matches_symbol_and_filters_auxiliary_codes():
    api = FakeTdxApi(
        futures_directory_routes(
            gfex=[
                instrument("gfex", "SIL8", "工业硅主连"),
                instrument("gfex", "SIL7", "工业硅次连"),
                instrument("gfex", "SIL9", "工业硅加权"),
                instrument("gfex", "SI2608", "工业硅2608"),
                instrument("gfex", "SI2609", "工业硅2609"),
            ],
            shfe=[instrument("shfe", "RBL8", "螺纹主连"), instrument("shfe", "RB2610", "螺纹2610")],
            comex=[instrument("comex", "GC00W", "COMEX黄金主连"), instrument("comex", "GC00Y", "COMEX黄金连续")],
            sge=[instrument("sge", "Au(T+D)", "Au(T+D)")],
        )
    )
    source = make_source(transport=api.transport())

    results = await source.fetch_futures_search("si", is_symbol=True)

    queried_markets = {params["market"] for path, params, _h in api.calls}
    assert queried_markets == set(FUTURES_SEARCH_TARGETS)
    assert "cffex" not in queried_markets  # CFFEX directory stays excluded
    # Auxiliary 次连 (L7) / 加权 (L9) filtered; deterministic (exchange, code) order.
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
            "expiration": "2026-09",
            "code": "SI2609",
            "name": "工业硅2609",
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


async def test_futures_search_by_chinese_name():
    api = FakeTdxApi(
        futures_directory_routes(
            shfe=[instrument("shfe", "RBL8", "螺纹主连"), instrument("shfe", "RB2610", "螺纹2610")],
        )
    )
    source = make_source(transport=api.transport())

    results = await source.fetch_futures_search("螺纹", is_symbol=False)

    assert [row["code"] for row in results] == ["RB2610", "RBL8"]
    assert {row["exchange"] for row in results} == {"SHFE"}


async def test_futures_search_matches_sge_user_alias():
    api = FakeTdxApi(
        futures_directory_routes(
            sge=[instrument("sge", "Au(T+D)", "Au(T+D)"), instrument("sge", "Au99.99", "黄金99.99")],
        )
    )
    source = make_source(transport=api.transport())

    results = await source.fetch_futures_search("AU9999", is_symbol=True)

    # The native SGE code "Au99.99" is only reachable through the user symbol.
    assert results == [
        {
            "symbol": "AU9999.SGE",
            "expiration": None,
            "code": "Au99.99",
            "name": "黄金99.99",
            "exchange": "SGE",
            "source": "tdx",
        },  # noqa: E501
    ]


async def test_futures_search_empty_query_returns_empty_without_requests():
    api = FakeTdxApi(futures_directory_routes())
    source = make_source(transport=api.transport())

    assert await source.fetch_futures_search("   ") == []
    assert api.calls == []


async def test_futures_search_any_market_failure_fails_whole_search():
    api = FakeTdxApi(
        futures_directory_routes(
            shfe=(503, {"error": {"code": "upstream_unavailable", "message": "候选主机均不可用"}}),
            gfex=[instrument("gfex", "SIL8", "工业硅主连")],
        )
    )
    source = make_source(transport=api.transport())

    with pytest.raises(SourceError, match="upstream_unavailable"):
        await source.fetch_futures_search("si", is_symbol=True)


async def test_futures_search_incomplete_directory_fails_whole_search():
    api = FakeTdxApi(instruments_route({market: [] for market in FUTURES_SEARCH_TARGETS}, directory_complete=False))
    source = make_source(transport=api.transport())

    with pytest.raises(SourceError, match="incomplete"):
        await source.fetch_futures_search("si", is_symbol=True)


async def test_futures_search_page_budget_exhaustion_raises():
    big_directory = [{"market": "comex", "code": f"GC{i:05d}", "name": None} for i in range(11_000)]
    api = FakeTdxApi(futures_directory_routes(comex=big_directory))
    source = make_source(transport=api.transport())

    with pytest.raises(SourceError, match="10-page budget"):
        await source.fetch_futures_search("GC", is_symbol=True)


async def test_equity_search_keyword_covers_five_markets_and_filters_desc_only():
    pages = {
        "cn_sh": [[instrument("cn_sh", "600519", "贵州茅台")]],
        "cn_sz": [[]],
        "hk": [[instrument("hk", "09999", "茅台国际控股")]],
        "hk_gem": [[]],
        "us": [[instrument("us", "MTXX", "Some Cap", desc="茅台 leveraged tracker")]],
    }
    api = FakeTdxApi(search_route(pages))
    source = make_source(transport=api.transport())

    results = await source.fetch_equity_search("茅台", is_symbol=False)

    queried = {params["market"] for path, params, _h in api.calls}
    assert queried == set(EQ_SEARCH_TARGETS)
    # Sorted by canonical symbol; the desc-only EX match is dropped.
    assert results == [
        {"symbol": "09999.HK", "name": "茅台国际控股", "exchange": "HK", "type": None, "source": "tdx"},
        {"symbol": "600519.XSHG", "name": "贵州茅台", "exchange": "XSHG", "type": None, "source": "tdx"},
    ]


async def test_equity_search_is_symbol_true_drops_name_only_matches():
    pages = {
        "cn_sh": [[]],
        "cn_sz": [[]],
        "hk": [[]],
        "hk_gem": [[]],
        "us": [[instrument("us", "AAPL", "Apple Inc."), instrument("us", "XYZ", "AAP Holdings Ltd.")]],
    }
    source = make_source(search_route(pages))

    results = await source.fetch_equity_search("AAP", is_symbol=True)

    assert results == [{"symbol": "AAPL", "name": "Apple Inc.", "exchange": "US", "type": None, "source": "tdx"}]


async def test_equity_search_us_dotted_code_stays_whole():
    pages = {
        "cn_sh": [[]],
        "cn_sz": [[]],
        "hk": [[]],
        "hk_gem": [[]],
        "us": [[instrument("us", "BRK.B", "Berkshire Class B")]],
    }
    source = make_source(search_route(pages))

    results = await source.fetch_equity_search("BRK.B", is_symbol=True)

    assert results == [
        {"symbol": "BRK.B", "name": "Berkshire Class B", "exchange": "US", "type": None, "source": "tdx"}
    ]


async def test_equity_search_hk_suffix_takes_info_fast_path():
    api = FakeTdxApi(info_route({("hk", "00700"): {"market": "hk", "code": "00700", "name": "騰訊控股"}}))
    source = make_source(transport=api.transport())

    results = await source.fetch_equity_search("700.HK", is_symbol=True)

    assert [(path, params["market"], params["code"]) for path, params, _h in api.calls] == [
        ("/api/v1/instruments/info", "hk", "00700")
    ]
    assert results == [{"symbol": "00700.HK", "name": "騰訊控股", "exchange": "HK", "type": None, "source": "tdx"}]


async def test_equity_search_bare_cn_code_fast_path_hits_first_market():
    api = FakeTdxApi(info_route({("cn_sh", "600519"): {"market": "cn_sh", "code": "600519", "name": "贵州茅台"}}))
    source = make_source(transport=api.transport())

    results = await source.fetch_equity_search("600519", is_symbol=True)

    queried = [(params["market"], params["code"]) for path, params, _h in api.calls]
    assert queried == [("cn_sh", "600519")]  # hit stops before trying cn_sz
    assert results == [{"symbol": "600519.XSHG", "name": "贵州茅台", "exchange": "XSHG", "type": None, "source": "tdx"}]


async def test_equity_search_fast_path_miss_falls_back_to_full_search():
    api = FakeTdxApi(
        {
            **info_route({}),  # every candidate misses (data=null is a normal miss)
            **search_route({"cn_sh": [[instrument("cn_sh", "600519", "贵州茅台")]]}),
        }
    )
    source = make_source(transport=api.transport())

    results = await source.fetch_equity_search("600519.XSHG", is_symbol=True)

    paths = [path for path, _params, _h in api.calls]
    assert paths[0] == "/api/v1/instruments/info"
    assert "/api/v1/instruments/search" in paths
    assert results == [{"symbol": "600519.XSHG", "name": "贵州茅台", "exchange": "XSHG", "type": None, "source": "tdx"}]


async def test_equity_search_info_target_mismatch_raises():
    api = FakeTdxApi(info_route({("hk", "00700"): {"market": "hk", "code": "00999", "name": "wrong"}}))
    source = make_source(transport=api.transport())

    with pytest.raises(SourceError, match="mismatched"):
        await source.fetch_equity_search("700.HK", is_symbol=True)


async def test_equity_search_empty_query_returns_empty_without_requests():
    api = FakeTdxApi(search_route({market: [] for market in EQ_SEARCH_TARGETS}))
    source = make_source(transport=api.transport())

    assert await source.fetch_equity_search("  ") == []
    assert api.calls == []


async def test_equity_search_multi_page_per_market():
    big_page = [instrument("cn_sh", f"60{i:04d}", "X") for i in range(1000)]
    tail_page = [instrument("cn_sh", f"61{i:04d}", "X") for i in range(3)]
    pages = {
        "cn_sh": [big_page, tail_page],
        "cn_sz": [[]],
        "hk": [[]],
        "hk_gem": [[]],
        "us": [[]],
    }
    source = make_source(search_route(pages))

    results = await source.fetch_equity_search("X", is_symbol=False)

    assert len(results) == 1003
    symbols = [row["symbol"] for row in results]
    assert symbols == sorted(symbols)


async def test_equity_search_result_budget_across_markets_raises():
    heavy = [{"market": "cn_sh", "code": f"60{i:04d}", "name": "A"} for i in range(6000)]
    heavy_sz = [{"market": "cn_sz", "code": f"00{i:05d}", "name": "A"} for i in range(6000)]
    pages = {
        "cn_sh": [heavy],
        "cn_sz": [heavy_sz],
        "hk": [[]],
        "hk_gem": [[]],
        "us": [[]],
    }
    source = make_source(search_route(pages))

    with pytest.raises(SourceError, match="result budget"):
        await source.fetch_equity_search("A", is_symbol=False)


async def test_equity_search_market_failure_cancels_in_flight_markets():
    import asyncio

    events = {"us_done": False}

    async def handle(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        if request.url.path == "/api/v1/instruments/search":
            if params.get("market") == "cn_sz":
                return httpx.Response(503, json={"error": {"code": "upstream_unavailable", "message": "down"}})
            if params.get("market") == "us":
                await asyncio.sleep(1.0)
                events["us_done"] = True
                return httpx.Response(200, json=envelope([]))
        return httpx.Response(200, json=envelope([], empty_page_meta(0, 0, complete=True)))

    source = make_source(transport=httpx.MockTransport(handle))

    with pytest.raises(SourceError, match="upstream_unavailable"):
        await source.fetch_equity_search("whatever")
    assert events["us_done"] is False  # the in-flight market was cancelled
